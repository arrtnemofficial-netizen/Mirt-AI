"""ManyChat webhook router."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from src.conf.config import settings
from src.core.logging import log_event, safe_preview
from src.integrations.manychat.webhook import ManychatPayloadError
from src.server.dependencies import get_cached_manychat_handler
from src.services.infra.webhook_dedupe import WebhookDedupeStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["manychat"])


def _extract_manychat_message_id(payload: dict[str, Any], message: dict[str, Any]) -> str | None:
    """Extract message ID for idempotency check."""
    for key in ("id", "message_id", "messageId"):
        value = message.get(key)
        if value:
            return str(value)

    for key in ("message_id", "messageId", "event_id", "eventId", "update_id", "updateId"):
        value = payload.get(key)
        if value:
            return str(value)

    return None


@router.post("/webhooks/manychat")
async def manychat_webhook(
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
    x_manychat_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Handle incoming ManyChat webhook payloads.

    Supports two modes:
    - Push mode (MANYCHAT_PUSH_MODE=true): Returns 202 immediately, processes async
    - Response mode (MANYCHAT_PUSH_MODE=false): Waits for AI, returns response
    """
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    inbound_token = x_manychat_token
    if not inbound_token and authorization:
        auth_value = authorization.strip()
        if auth_value.lower().startswith("bearer "):
            inbound_token = auth_value[7:].strip()
        else:
            inbound_token = auth_value

    if verify_token and verify_token != inbound_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    # Push mode: return immediately, process in background
    if settings.MANYCHAT_PUSH_MODE:
        from src.integrations.manychat.async_service import get_manychat_async_service
        from src.server.dependencies import get_session_store

        try:
            trace_id = str(uuid.uuid4())

            # Extract user info from payload
            subscriber = payload.get("subscriber") or payload.get("user") or {}
            message = payload.get("message") or payload.get("data", {}).get("message") or {}

            user_id = str(subscriber.get("id") or subscriber.get("user_id") or "unknown")
            text = ""
            image_url = None

            if isinstance(message, dict):
                text = message.get("text") or message.get("content") or ""
                # Extract image from attachments
                for attachment in message.get("attachments", []):
                    if attachment.get("type") == "image":
                        image_url = attachment.get("payload", {}).get("url")
                        break
                if not image_url:
                    image_url = message.get("image") or message.get("image_url")

            # Also check data.image_url
            if not image_url:
                data = payload.get("data", {})
                image_url = data.get("image_url") or data.get("photo_url")

            channel = payload.get("type") or "instagram"

            if not text and not image_url:
                raise HTTPException(status_code=400, detail="Missing message text or image")

            # IDEMPOTENCY (DB-backed, 24h TTL)
            message_id = None
            if isinstance(message, dict):
                message_id = _extract_manychat_message_id(payload, message)

            if message_id:
                from src.services.infra.supabase_client import get_supabase_client

                db = get_supabase_client()
                if db:
                    dedupe_store = WebhookDedupeStore(db, ttl_hours=24)

                    is_duplicate = dedupe_store.check_and_mark(
                        user_id=user_id,
                        message_id=message_id,
                        text=text,
                        image_url=image_url,
                    )

                    if is_duplicate:
                        logger.info(
                            "[MANYCHAT] Duplicate delivery ignored (push mode) user=%s message_id=%s",
                            user_id,
                            message_id,
                        )
                        return {"status": "accepted"}
                else:
                    logger.warning(
                        "[MANYCHAT] Supabase disabled, skipping dedupe (push mode) user=%s message_id=%s",
                        user_id,
                        message_id,
                    )

            # DURABLE PROCESSING (Celery or BackgroundTasks fallback)
            if settings.CELERY_ENABLED and getattr(settings, "MANYCHAT_USE_CELERY", False):
                from src.workers.tasks.manychat import process_manychat_message

                task = process_manychat_message.delay(
                    user_id=user_id,
                    text=text or "",
                    image_url=image_url,
                    channel=channel,
                    subscriber_data=subscriber,
                    trace_id=trace_id,
                )

                log_event(
                    logger,
                    event="manychat_task_scheduled",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                    task_id=task.id,
                )

                return {"status": "accepted"}
            else:
                store = get_session_store()
                service = get_manychat_async_service(store)

                background_tasks.add_task(
                    service.process_message_async,
                    user_id=user_id,
                    text=text or "",
                    image_url=image_url,
                    channel=channel,
                    subscriber_data=subscriber,
                    trace_id=trace_id,
                )

                log_event(
                    logger,
                    event="manychat_task_scheduled",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                    status="background_tasks",
                )

            log_event(
                logger,
                event="manychat_message_accepted",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
            )
            return {"status": "accepted"}

        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[MANYCHAT] Error in push mode: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Response mode: wait for AI and return response
    handler = get_cached_manychat_handler()
    try:
        return await handler.handle(payload)
    except ManychatPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
