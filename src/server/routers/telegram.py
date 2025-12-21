"""Telegram webhook router.

Extracted from main.py to reduce God Object pattern.
"""

from __future__ import annotations

import logging

from aiogram.types import Update
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.conf.config import settings
from src.server.dependencies import get_bot, get_cached_dispatcher

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


@router.post(settings.TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> JSONResponse:
    """Handle incoming Telegram webhook updates (AI-only \u0432\u0456\u0434\u043f\u043e\u0432\u0456\u0434\u0456)."""
    bot = get_bot()
    dp = get_cached_dispatcher()

    body = await request.json()
    update = Update.model_validate(body)
    await dp.feed_update(bot=bot, update=update)
    return JSONResponse({"ok": True})
