"""Aiogram-based Telegram bot that wraps the LangGraph app."""
from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.conf.config import settings
from src.core.models import AgentResponse
from src.services.graph import app as graph_app
from src.services.renderer import render_agent_response_text
from src.services.session_store import InMemorySessionStore


def build_dispatcher(store: InMemorySessionStore, runner=graph_app) -> Dispatcher:
    """Create a Dispatcher with handlers bound to the shared store."""

    dp = Dispatcher()

    @dp.message(CommandStart())
    async def handle_start(message: Message) -> None:
        await message.answer(
            "Привіт! Я стиліст MIRT. Напиши, що шукаєш, і підберу варіанти."
        )

    @dp.message(F.text)
    async def handle_text(message: Message) -> None:
        await _process_incoming(message, store, runner)

    @dp.message(F.photo)
    async def handle_photo(message: Message) -> None:
        caption = message.caption or ""
        description = caption if caption else "Фото отримано. Опишіть, що шукаєте."
        await _process_incoming(message, store, runner, override_text=description)

    return dp


def build_bot() -> Bot:
    """Instantiate Bot from settings."""

    return Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())


async def _process_incoming(
    message: Message,
    store: InMemorySessionStore,
    runner,
    override_text: str | None = None,
) -> None:
    """Transform Telegram message into AgentState, invoke graph, and reply."""

    text = override_text or message.text or ""
    session_id = str(message.chat.id)

    state = store.get(session_id)
    state["messages"].append({"role": "user", "content": text})
    state["metadata"].setdefault("session_id", session_id)

    result_state = await runner.ainvoke(state)
    store.save(session_id, result_state)

    agent_json = result_state["messages"][-1]["content"]
    agent_response = AgentResponse.model_validate_json(agent_json)
    await _dispatch_to_telegram(message, agent_response)


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


def run_polling(store: InMemorySessionStore | None = None) -> None:
    """Convenience entry point for local polling runs."""

    session_store = store or InMemorySessionStore()
    bot = build_bot()
    dp = build_dispatcher(session_store)
    asyncio.run(dp.start_polling(bot))


if __name__ == "__main__":
    run_polling()
