"""ASGI app exposing Telegram and ManyChat webhooks."""
from __future__ import annotations

from typing import Any, Dict

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.bot.telegram_bot import build_bot, build_dispatcher
from src.conf.config import settings
from src.integrations.manychat.webhook import ManychatPayloadError, ManychatWebhook
from src.services.session_store import InMemorySessionStore, SessionStore
from src.services.supabase_store import create_supabase_store

app = FastAPI(title="MIRT AI Webhooks")

def _select_store() -> SessionStore:
    supabase_store = create_supabase_store()
    if supabase_store:
        return supabase_store
    return InMemorySessionStore()


store = _select_store()
bot = build_bot()
dp = build_dispatcher(store)
manychat_handler = ManychatWebhook(store)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post(settings.TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> JSONResponse:
    body = await request.json()
    update = Update.model_validate(body)
    await dp.feed_update(bot=bot, update=update)
    return JSONResponse({"ok": True})


@app.post("/webhooks/manychat")
async def manychat_webhook(
    payload: Dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
) -> Dict[str, Any]:
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    if verify_token and verify_token != x_manychat_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")
    try:
        return await manychat_handler.handle(payload)
    except ManychatPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.on_event("startup")
async def configure_webhook() -> None:
    """Register Telegram webhook on startup if URL is provided."""

    base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    if not base_url or not settings.TELEGRAM_BOT_TOKEN.get_secret_value():
        return
    full_url = f"{base_url}{settings.TELEGRAM_WEBHOOK_PATH}"
    await bot.set_webhook(full_url)
