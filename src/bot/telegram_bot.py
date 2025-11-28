"""Aiogram-based Telegram bot that wraps the LangGraph app.

Features:
- Text and photo message handling
- Quick Reply keyboard based on conversation state
- Product photo sending
- Centralized error handling
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from src.agents.graph_v2 import get_active_graph
from src.conf.config import settings
from src.services.conversation import ConversationHandler, create_conversation_handler
from src.services.message_store import MessageStore, create_message_store
from src.services.renderer import render_agent_response_text
from src.services.session_store import InMemorySessionStore, SessionStore


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Quick Reply Keyboards по станах (використовує state_machine)
# ---------------------------------------------------------------------------
import contextlib

from src.core.state_machine import EscalationLevel, State, get_keyboard_for_state, normalize_state


if TYPE_CHECKING:
    from src.core.models import AgentResponse


def build_keyboard(
    current_state: str, escalation_level: str = "NONE"
) -> ReplyKeyboardMarkup | None:
    """Build Reply Keyboard based on conversation state using centralized state_machine."""

    # Normalize state and escalation
    state = normalize_state(current_state)
    esc_level = EscalationLevel.NONE
    with contextlib.suppress(ValueError):
        esc_level = EscalationLevel(escalation_level.upper())

    # Get keyboard config from state_machine
    keyboard_config = get_keyboard_for_state(state, esc_level)

    if keyboard_config is None:
        return None

    # Handle keyboard removal for end states
    if state in (State.STATE_7_END,):
        return ReplyKeyboardRemove()

    # Build Telegram keyboard from config
    buttons: list[list[KeyboardButton]] = []
    for row in keyboard_config.buttons:
        buttons.append([KeyboardButton(text=btn) for btn in row])

    if not buttons:
        return None

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=keyboard_config.one_time,
    )


def build_dispatcher(
    store: SessionStore,
    message_store: MessageStore | None = None,
    runner=None,
) -> Dispatcher:
    """Create a Dispatcher with handlers bound to the shared store."""
    dp = Dispatcher()
    msg_store = message_store or create_message_store()

    # Use active graph based on USE_GRAPH_V2 feature flag
    active_runner = runner or get_active_graph()

    # Create centralized conversation handler
    conversation_handler = create_conversation_handler(
        session_store=store,
        message_store=msg_store,
        runner=active_runner,
    )

    @dp.message(CommandStart())
    async def handle_start(message: Message) -> None:
        await message.answer("Привіт! Я стиліст MIRT. Напиши, що шукаєш, і підберу варіанти.")

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
    """Send formatted agent response back to the chat with keyboard."""

    # Build keyboard based on state
    keyboard = build_keyboard(
        current_state=agent_response.metadata.current_state,
        escalation_level=agent_response.metadata.escalation_level,
    )

    text_chunks = render_agent_response_text(agent_response)

    # Send text messages (last one with keyboard)
    for i, chunk in enumerate(text_chunks):
        is_last_text = (i == len(text_chunks) - 1) and not agent_response.products
        await message.answer(
            chunk,
            reply_markup=keyboard if is_last_text else None,
        )

    # Send product photos (last one with keyboard)
    for i, product in enumerate(agent_response.products):
        if product.photo_url:
            is_last = i == len(agent_response.products) - 1
            await message.answer_photo(
                photo=product.photo_url,
                caption=f"{product.name} - {product.price} грн",
                reply_markup=keyboard if is_last else None,
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
