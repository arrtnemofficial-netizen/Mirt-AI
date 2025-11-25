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
from src.services.message_store import create_message_store
from src.services.summarization import run_retention

app = FastAPI(title="MIRT AI Webhooks")

def _select_store() -> SessionStore:
    supabase_store = create_supabase_store()
    if supabase_store:
        return supabase_store
    return InMemorySessionStore()


store = _select_store()
message_store = create_message_store()
bot = build_bot()
dp = build_dispatcher(store, message_store)
manychat_handler = ManychatWebhook(store, message_store=message_store)


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


@app.post("/automation/mirt-summarize-prod-v1")
async def run_summarization(payload: Dict[str, Any]) -> Dict[str, Any]:
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    summary = run_retention(session_id, message_store)
    return {"session_id": session_id, "summary": summary, "status": "ok"}


@app.on_event("startup")
async def configure_webhook() -> None:
    """Register Telegram webhook on startup if URL is provided."""

    base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    if not base_url or not settings.TELEGRAM_BOT_TOKEN.get_secret_value():
        return
    full_url = f"{base_url}{settings.TELEGRAM_WEBHOOK_PATH}"
    await bot.set_webhook(full_url)
