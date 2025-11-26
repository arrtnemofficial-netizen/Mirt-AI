"""Aiogram-based Telegram bot that wraps the LangGraph app."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.agents.graph import app as graph_app
from src.conf.config import settings
from src.core.models import AgentResponse
from src.services.conversation import ConversationHandler, create_conversation_handler
from src.services.message_store import MessageStore, create_message_store
from src.services.renderer import render_agent_response_text
from src.services.session_store import InMemorySessionStore, SessionStore

logger = logging.getLogger(__name__)


def build_dispatcher(
    store: SessionStore,
    message_store: MessageStore | None = None,
    runner=graph_app,
) -> Dispatcher:
    """Create a Dispatcher with handlers bound to the shared store."""
    dp = Dispatcher()
    msg_store = message_store or create_message_store()

    # Create centralized conversation handler
    conversation_handler = create_conversation_handler(
        session_store=store,
        message_store=msg_store,
        runner=runner,
    )

    @dp.message(CommandStart())
    async def handle_start(message: Message) -> None:
        await message.answer(
            "Привіт! Я стиліст MIRT. Напиши, що шукаєш, і підберу варіанти."
        )

    @dp.message(F.text)
    async def handle_text(message: Message) -> None:
        await _process_incoming(message, conversation_handler)

    @dp.message(F.photo)
    async def handle_photo(message: Message) -> None:
        caption = message.caption or ""
        description = caption if caption else "Фото отримано. Опишіть, що шукаєте."
        await _process_incoming(message, conversation_handler, override_text=description)

    return dp


def build_bot() -> Bot:
    """Instantiate Bot from settings."""
    return Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())


async def _process_incoming(
    message: Message,
    handler: ConversationHandler,
    override_text: str | None = None,
) -> None:
    """Process incoming Telegram message using ConversationHandler."""
    text = override_text or message.text or ""
    session_id = str(message.chat.id)

    # Use centralized handler - all error handling is done internally
    result = await handler.process_message(session_id, text)

    if result.is_fallback:
        logger.warning(
            "Fallback response for session %s: %s",
            session_id,
            result.error,
        )

    await _dispatch_to_telegram(message, result.response)


async def _dispatch_to_telegram(message: Message, agent_response: AgentResponse) -> None:
    """Send formatted agent response back to the chat."""

    text_chunks = render_agent_response_text(agent_response)
    for chunk in text_chunks:
        await message.answer(chunk)

    for product in agent_response.products:
        if product.photo_url:
            await message.answer_photo(
                photo=product.photo_url,
                caption=product.name,
            )


def run_polling(store: SessionStore | None = None) -> None:
    """Convenience entry point for local polling runs."""

    session_store = store or InMemorySessionStore()
    message_store = create_message_store()
    bot = build_bot()
    dp = build_dispatcher(session_store, message_store)
    asyncio.run(dp.start_polling(bot))


if __name__ == "__main__":
    run_polling()
