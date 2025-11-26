"""ASGI app exposing Telegram and ManyChat webhooks.

This module uses proper FastAPI dependency injection and lifespan management
instead of global singletons.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from aiogram.types import Update
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.conf.config import settings
from src.core.logging import setup_logging
from src.integrations.manychat.webhook import ManychatPayloadError
from src.server.dependencies import (
    BotDep,
    DispatcherDep,
    ManychatHandlerDep,
    MessageStoreDep,
    get_bot,
    get_cached_dispatcher,
    get_cached_manychat_handler,
    get_message_store,
)
from src.server.middleware import setup_middleware
from src.services.followups import run_followups
from src.services.summarization import run_retention

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown events."""
    # Configure logging (JSON in production, pretty in development)
    is_production = settings.PUBLIC_BASE_URL != "http://localhost:8000"
    setup_logging(
        level="INFO",
        json_format=is_production,
        service_name="mirt-ai",
    )

    # Startup
    logger.info("Starting MIRT AI Webhooks server")

    # Register Telegram webhook if configured
    base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()

    if base_url and token and base_url != "http://localhost:8000":
        try:
            bot = get_bot()
            full_url = f"{base_url}{settings.TELEGRAM_WEBHOOK_PATH}"
            await bot.set_webhook(full_url)
            logger.info("Telegram webhook registered: %s", full_url)
        except Exception as e:
            logger.error("Failed to register Telegram webhook: %s", e)

    yield

    # Shutdown
    logger.info("Shutting down MIRT AI Webhooks server")


app = FastAPI(
    title="MIRT AI Webhooks",
    description="AI-powered shopping assistant webhooks for Telegram and ManyChat",
    version="1.0.0",
    lifespan=lifespan,
)

# Setup middleware (rate limiting, request logging)
setup_middleware(app, enable_rate_limit=True, enable_logging=True)


@app.get("/health")
async def health() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post(settings.TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> JSONResponse:
    """Handle incoming Telegram webhook updates."""
    bot = get_bot()
    dp = get_cached_dispatcher()

    body = await request.json()
    update = Update.model_validate(body)
    await dp.feed_update(bot=bot, update=update)
    return JSONResponse({"ok": True})


@app.post("/webhooks/manychat")
async def manychat_webhook(
    payload: Dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
) -> Dict[str, Any]:
    """Handle incoming ManyChat webhook payloads."""
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    if verify_token and verify_token != x_manychat_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    handler = get_cached_manychat_handler()
    try:
        return await handler.handle(payload)
    except ManychatPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/automation/mirt-summarize-prod-v1")
async def run_summarization(
    payload: Dict[str, Any],
    message_store: MessageStoreDep,
) -> Dict[str, Any]:
    """Summarize and prune old messages for a session."""
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    summary = run_retention(session_id, message_store)
    return {"session_id": session_id, "summary": summary, "status": "ok"}


@app.post("/automation/mirt-followups-prod-v1")
async def trigger_followups(
    payload: Dict[str, Any],
    message_store: MessageStoreDep,
) -> Dict[str, Any]:
    """Trigger follow-up messages for inactive sessions."""
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    schedule_hours = payload.get("schedule_hours")
    if schedule_hours is not None and not isinstance(schedule_hours, list):
        raise HTTPException(status_code=400, detail="schedule_hours must be a list of integers")

    followup = run_followups(session_id, message_store, schedule_hours=schedule_hours)
    return {
        "session_id": session_id,
        "followup_created": bool(followup),
        "content": followup.content if followup else None,
        "tags": followup.tags if followup else [],
        "status": "ok",
    }
