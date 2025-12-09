"""Aiogram-based Telegram bot that wraps the LangGraph app.

Features:
- Text and photo message handling
- Без бот-клавіатур: AI повністю формує контент відповіді
- Product photo sending
- Centralized error handling
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from src.agents import get_active_graph  # Fixed: was graph_v2
from src.conf.config import settings
from src.core.state_machine import normalize_state
from src.services.conversation import ConversationHandler, create_conversation_handler
from src.services.message_store import MessageStore, create_message_store
from src.services.renderer import render_agent_response_text
from src.services.session_store import InMemorySessionStore, SessionStore


if TYPE_CHECKING:
    from src.core.models import AgentResponse


logger = logging.getLogger(__name__)


def build_dispatcher(
    store: SessionStore,
    message_store: MessageStore | None = None,
    runner=None,
) -> Dispatcher:
    """Create a Dispatcher with handlers bound to the shared store."""
    dp = Dispatcher()
    msg_store = message_store or create_message_store()

    active_runner = runner or get_active_graph()

    # Create centralized conversation handler
    conversation_handler = create_conversation_handler(
        session_store=store,
        message_store=msg_store,
        runner=active_runner,
    )

    @dp.message(CommandStart())
    async def handle_start(message: Message) -> None:
        """Старт діалогу: м'який ресет стану.

        Використовується при першому запуску або коли користувач сам натиснув /start.
        """

        session_id = str(message.chat.id)
        store.save(
            session_id,
            {
                "messages": [],
                "metadata": {"session_id": session_id},
                "current_state": "STATE_0_INIT",
            },
        )
        await message.answer("Можемо почати спілкування!")

    @dp.message(Command("restart"))
    async def handle_restart(message: Message) -> None:
        """Жорсткий ресет: повністю очистити сесію.

        - Перезаписує state в SessionStore (Supabase / in-memory)
        - Видаляє історію повідомлень з MessageStore
        """

        session_id = str(message.chat.id)

        # 1) Скидаємо стан розмови в SessionStore
        store.save(
            session_id,
            {
                "messages": [],
                "metadata": {"session_id": session_id},
                "current_state": "STATE_0_INIT",
            },
        )

        # 2) Видаляємо історію повідомлень, якщо сховище це підтримує
        try:
            delete_fn = getattr(msg_store, "delete", None)
            if callable(delete_fn):
                delete_fn(session_id)
        except Exception as e:
            logger.warning("Failed to delete message history for session %s: %s", session_id, e)

        await message.answer(
            "Сесію повністю перезапустила 🤍 Можемо почати з нуля. Надішліть фото або запитання."
        )

    @dp.message(F.text)
    async def handle_text(message: Message) -> None:
        await _process_incoming(message, conversation_handler)

    @dp.message(F.photo)
    async def handle_photo(message: Message) -> None:
        caption = message.caption or ""
        description = caption if caption else ""

        # Get photo URL from Telegram
        photo = message.photo[-1]  # Get largest photo
        file = await message.bot.get_file(photo.file_id)
        image_url = f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN.get_secret_value()}/{file.file_path}"

        await _process_incoming(
            message,
            conversation_handler,
            override_text=description,
            has_image=True,
            image_url=image_url,
        )

    return dp


def build_bot() -> Bot:
    """Instantiate Bot from settings."""
    return Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())


async def _process_incoming(
    message: Message,
    handler: ConversationHandler,
    override_text: str | None = None,
    has_image: bool = False,
    image_url: str | None = None,
) -> None:
    """Process incoming Telegram message using ConversationHandler."""
    text = override_text or message.text or ""
    session_id = str(message.chat.id)

    # Build extra metadata for photos
    extra_metadata = None
    if has_image:
        extra_metadata = {
            "has_image": True,
            "image_url": image_url,
        }

    # Log incoming message
    logger.info(
        "[SESSION %s] 📩 Incoming: text='%s', has_image=%s",
        session_id,
        text[:50] if text else "<empty>",
        has_image,
    )

    # Use centralized handler - all error handling is done internally
    result = await handler.process_message(session_id, text, extra_metadata=extra_metadata)

    # Log state and response
    current_state = result.state.get("current_state", "UNKNOWN") if result.state else "NO_STATE"
    identified_product = result.state.get("identified_product") if result.state else None
    logger.info(
        "[SESSION %s] 📊 State: %s | Product: %s | Fallback: %s",
        session_id,
        current_state,
        identified_product or "<none>",
        result.is_fallback,
    )

    if result.is_fallback:
        logger.warning(
            "[SESSION %s] ⚠️ Fallback response: %s",
            session_id,
            result.error,
        )

    await _dispatch_to_telegram(message, result.response, session_id)


async def _dispatch_to_telegram(
    message: Message, agent_response: AgentResponse, session_id: str = ""
) -> None:
    """Send formatted agent response back to the chat (без бот-клавіатури)."""

    # Log outgoing response
    response_preview = ""
    if agent_response.messages:
        response_preview = (
            agent_response.messages[0].content[:80] if agent_response.messages[0].content else ""
        )
    logger.info(
        "[SESSION %s] 📤 Response: state=%s, products=%d, msg='%s...'",
        session_id,
        agent_response.metadata.current_state,
        len(agent_response.products),
        response_preview,
    )

    text_chunks = render_agent_response_text(agent_response)

    # Send text messages
    for i, chunk in enumerate(text_chunks):
        if not chunk or not chunk.strip():
            continue
        await message.answer(chunk)

    # Send product photos only for vision/photo-ident responses to avoid повторних фото
    if agent_response.metadata.intent == "PHOTO_IDENT":
        for i, product in enumerate(agent_response.products):
            if product.photo_url:
                await message.answer_photo(
                    photo=product.photo_url,
                    caption="",  # без дублювання тексту/ціни
                )


async def run_polling(store: SessionStore | None = None) -> None:
    """Convenience entry point for local polling runs."""
    # Configure logging to show INFO level for our modules
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Reduce noise from external libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    print("🚀 Starting Telegram bot with INFO logging enabled...")

    from src.services.supabase_store import create_supabase_store

    # Try to use Supabase store if not provided
    if store is None:
        store = create_supabase_store()

    if store is None:
        print(
            "⚠️ Using InMemorySessionStore - session state will be lost on restart!\n"
            "   Set SUPABASE_URL and SUPABASE_API_KEY for persistent session storage."
        )
        session_store = InMemorySessionStore()
    else:
        print("✅ Using SupabaseSessionStore - session state is persistent.")
        session_store = store

    message_store = create_message_store()
    bot = build_bot()
    dp = build_dispatcher(session_store, message_store)

    # Check if there's already a running bot instance
    try:
        # Try to get updates - if successful, no conflict
        await bot.get_updates(limit=1, timeout=1)
        # Success means no conflict, proceed with polling
    except Exception as e:
        # Check for conflict error specifically
        if "Conflict" in str(e) or "terminated by other" in str(e):
            logger.warning("Another bot instance is already running. Stopping to avoid conflicts.")
            print("Another bot instance is already running. Stopping to avoid conflicts.")
            return
        # Other errors - log but proceed
        logger.debug("get_updates check failed: %s", e)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run_polling())
