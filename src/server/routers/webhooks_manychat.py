"""ManyChat webhook endpoints."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from src.conf.config import settings
from src.core.logging import log_event
from src.integrations.manychat.webhook import ManychatPayloadError
from src.server.dependencies import (
    MessageStoreDep,
)
from src.server.routers.common import extract_inbound_token, extract_manychat_message_id
from src.server.routers.schemas import IMAGE_URL_PATTERN
from src.services.webhook import WebhookDedupeStore


router = APIRouter()
logger = logging.getLogger(__name__)


def _generate_followup_text(current_state: str, last_product: str = "") -> str | None:
    """Generate follow-up message based on conversation state.

    Returns None if no follow-up needed (e.g., order completed).
    """
    followup_templates = {
        "STATE_1_DISCOVERY": "Привіт! 🤍 Можливо, підказати щось з одягу для дитини?",
        "STATE_2_VISION": "Чи сподобалась модель? Можу показати інші кольори або розміри 🤍",
        "STATE_3_SIZE_COLOR": "Підказати з розміром? Напишіть зріст дитини — підберу найкращий варіант 📏",
        "STATE_4_OFFER": f"Ще раздумуєте над {last_product if last_product else 'замовленням'}? Можу щось уточнити? 🤍",
        "STATE_5_PAYMENT_DELIVERY": "Чекаю на дані для доставки: ПІБ, телефон, місто та відділення Нової Пошти 📦",
    }

    # No follow-up for these states
    no_followup_states = {
        "STATE_0_INIT",  # Not started yet
        "STATE_6_UPSELL",  # Already upselling
        "STATE_7_END",  # Order completed
        "STATE_8_COMPLAINT",  # Complaint handling
    }

    if current_state in no_followup_states:
        return None

    return followup_templates.get(current_state, "Чим можу допомогти? 🤍")


def _strip_manychat_prefix(text: str) -> str:
    """Strip ManyChat/n8n '.;' prefix that can repeat."""
    msg = (text or "").strip()
    while msg.startswith(".;"):
        msg = msg[2:].lstrip()
    return msg


def _extract_text_and_image(message: Any) -> tuple[str, str | None]:
    """Extract message text and image URL from webhook/external request payloads."""
    text = ""
    image_url = None

    if isinstance(message, dict):
        text = message.get("text") or message.get("content") or ""
        for attachment in message.get("attachments", []):
            if attachment.get("type") == "image":
                image_url = attachment.get("payload", {}).get("url")
                break
        if not image_url:
            image_url = message.get("image") or message.get("image_url")
    elif isinstance(message, str):
        text = message

    text = _strip_manychat_prefix(text)

    if not image_url and text:
        match = IMAGE_URL_PATTERN.search(text)
        if match:
            image_url = match.group(0)

    if image_url and text:
        text = text.replace(image_url, "").strip()
        text = _strip_manychat_prefix(text)

    return text, image_url


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
    inbound_token = extract_inbound_token(x_manychat_token, authorization)

    if verify_token and verify_token != inbound_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    # Push mode (or external request): return immediately, process in background
    is_external_request = isinstance(payload.get("message"), str) and (
        payload.get("sessionId") or payload.get("session_id") or payload.get("clientId") or payload.get("client_id")
    )
    if settings.MANYCHAT_PUSH_MODE or is_external_request:
        from src.integrations.manychat.async_service import get_manychat_async_service
        from src.server.dependencies import get_session_store

        try:
            trace_id = str(uuid.uuid4())

            # Extract user info from payload
            subscriber = payload.get("subscriber") or payload.get("user") or {}
            message = payload.get("message") or payload.get("data", {}).get("message") or {}

            user_id = str(
                subscriber.get("id")
                or subscriber.get("user_id")
                or payload.get("sessionId")
                or payload.get("session_id")
                or payload.get("clientId")
                or payload.get("client_id")
                or "unknown"
            )
            text, image_url = _extract_text_and_image(message)

            # Also check data.image_url
            if not image_url:
                data = payload.get("data", {})
                image_url = data.get("image_url") or data.get("photo_url")

            channel = payload.get("type") or "instagram"

            if not text and not image_url:
                raise HTTPException(status_code=400, detail="Missing message text or image")

            # -----------------------------------------------------------------
            # IDEMPOTENCY (DB-backed, 24h TTL)
            # -----------------------------------------------------------------
            message_id = None
            if isinstance(message, dict):
                message_id = extract_manychat_message_id(payload, message)

            if message_id:
                # Use PostgreSQL for webhook deduplication
                dedupe_store = WebhookDedupeStore(ttl_hours=24)

                # Check for duplicates using async DB store
                is_duplicate = await dedupe_store.check_and_mark_async(
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

            # -----------------------------------------------------------------
            # BACKGROUND PROCESSING (FastAPI BackgroundTasks)
            # -----------------------------------------------------------------
            # Note: Celery is only used for followups and summarization.
            # ManyChat message processing uses BackgroundTasks for simplicity.
            store = get_session_store()
            service = get_manychat_async_service(store)

            background_tasks.add_task(
                service.process_message_async,
                user_id=user_id,
                text=text or "",
                image_url=image_url,
                channel=channel,
                subscriber_data=subscriber,  # Pass subscriber data for username
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
    from src.server.dependencies import get_cached_manychat_handler

    handler = get_cached_manychat_handler()
    try:
        return await handler.handle(payload)
    except ManychatPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/webhooks/manychat/followup")
async def manychat_followup(
    payload: dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
    message_store: MessageStoreDep = None,
) -> dict[str, Any]:
    """ManyChat follow-up endpoint called after Smart Delay.

    This endpoint checks if the user has responded since the last AI message.
    If not, it generates a follow-up message.

    ManyChat Conditions can check:
    - needs_followup: true/false
    - followup_text: message to send
    - current_state: AI conversation state

    Payload expected:
    {
        "subscriber": {"id": "12345"},
        "custom_fields": {
            "ai_state": "STATE_4_OFFER",
            "last_product": "Сукня Анна"
        }
    }
    """
    # Verify token
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    if verify_token and verify_token != x_manychat_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    # Extract subscriber ID
    subscriber = payload.get("subscriber") or payload.get("user") or {}
    user_id = str(subscriber.get("id") or subscriber.get("user_id") or "unknown")

    if user_id == "unknown":
        return {
            "needs_followup": False,
            "reason": "unknown_user",
        }

    # Get custom fields from ManyChat
    custom_fields = payload.get("custom_fields") or {}
    current_state = custom_fields.get("ai_state", "STATE_0_INIT")
    last_product = custom_fields.get("last_product", "")

    # Generate follow-up based on state
    followup_text = _generate_followup_text(current_state, last_product)
    needs_followup = followup_text is not None

    # Build response for ManyChat Conditions
    return {
        "needs_followup": needs_followup,
        "followup_text": followup_text or "",
        "current_state": current_state,
        "set_field_values": [
            {"field_name": "followup_sent", "field_value": "true" if needs_followup else "false"},
        ],
        "add_tag": ["followup_sent"] if needs_followup else [],
    }


# Endpoint /webhooks/manychat/create-order removed - CRM orders integration disabled
# Only Sitniks chat status updates are supported (no order creation)

