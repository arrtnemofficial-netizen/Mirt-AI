"""API v1 endpoints."""

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from src.conf.config import settings
from src.core.logging import log_event, safe_preview
from src.server.routers.common import extract_inbound_token
from src.server.routers.schemas import ApiV1MessageRequest, SitniksUpdateRequest


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/v1/messages", status_code=202)
async def api_v1_messages(
    request: Request,
    background_tasks: BackgroundTasks,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Handle messages from ManyChat External Request.

    Supports formats:
    - {type, clientId, message, image_url}
    - {sessionId, name, message} (n8n format)
    """
    raw_body = await request.body()
    log_event(
        logger,
        event="api_v1_payload_received",
        text_len=len(raw_body or b""),
        text_preview=safe_preview(raw_body.decode("utf-8", errors="replace"), 200),
    )

    try:
        raw_json = json.loads(raw_body)
        logger.debug("[API_V1] RAW keys=%s", list(raw_json.keys()))
    except json.JSONDecodeError as e:
        log_event(
            logger,
            event="api_v1_payload_parsed",
            level="warning",
            root_cause="INVALID_JSON",
            error=safe_preview(e, 200),
        )
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    try:
        payload = ApiV1MessageRequest.model_validate(raw_json)
        log_event(
            logger,
            event="api_v1_payload_parsed",
            user_id=str(payload.client_id),
            channel=payload.type or "instagram",
            text_len=len(payload.message or ""),
            text_preview=safe_preview(payload.message, 160),
            has_image=bool(payload.image_url),
            image_url_preview=safe_preview(payload.image_url, 100),
        )
    except Exception as e:
        logger.error("[API_V1] ❌ Pydantic validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    # === STEP 3: Auth check ===
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    inbound_token = extract_inbound_token(x_api_key, authorization)

    if verify_token and verify_token != inbound_token:
        logger.warning(
            "[API_V1] ⛔ Auth failed: expected=%s, got=%s",
            verify_token[:10] if verify_token else None,
            inbound_token[:10] if inbound_token else None,
        )
        raise HTTPException(status_code=401, detail="Invalid API token")

    # === STEP 4: Schedule background processing ===
    from src.integrations.manychat.async_service import get_manychat_async_service
    from src.server.dependencies import get_session_store

    store = get_session_store()
    service = get_manychat_async_service(store)

    user_id = str(payload.client_id)
    channel = payload.type or "instagram"

    trace_id = str(uuid.uuid4())

    log_event(
        logger,
        event="api_v1_task_scheduled",
        trace_id=trace_id,
        user_id=user_id,
        channel=channel,
        text_len=len(payload.message or ""),
        text_preview=safe_preview(payload.message, 160),
        has_image=bool(payload.image_url),
        image_url_preview=safe_preview(payload.image_url, 100),
    )

    background_tasks.add_task(
        service.process_message_async,
        user_id=user_id,
        text=payload.message or "",
        image_url=payload.image_url,
        channel=channel,
        trace_id=trace_id,
    )

    logger.debug("[API_V1] returning 202")
    return {"status": "accepted"}


@router.post("/api/v1/sitniks/update-status")
async def sitniks_update_status(
    payload: SitniksUpdateRequest,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Update Sitniks CRM chat status from external JS node.

    This endpoint allows ManyChat/n8n JS nodes to trigger status updates
    after the agent response is generated.

    Stages:
    - first_touch: Set "Взято в роботу" + assign AI Manager
    - give_requisites: Set "Виставлено рахунок"
    - escalation: Set "AI Увага" + assign human manager

    Auth: X-API-Key header or Authorization: Bearer token
    (uses MANYCHAT_VERIFY_TOKEN)

    Example JS (n8n):
    ```javascript
    const response = await fetch('https://your-server/api/v1/sitniks/update-status', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-API-Key': 'your-token'
        },
        body: JSON.stringify({
            stage: 'first_touch',
            user_id: '12345',
            instagram_username: 'user123'
        })
    });
    ```
    """
    from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service

    # Auth check (same as /api/v1/messages)
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    inbound_token = extract_inbound_token(x_api_key, authorization)

    if verify_token and verify_token != inbound_token:
        raise HTTPException(status_code=401, detail="Invalid API token")

    service = get_sitniks_chat_service()

    if not service.enabled:
        return {
            "success": False,
            "error": "Sitniks integration not configured",
            "stage": payload.stage,
        }

    stage = payload.stage.lower().replace("-", "_").replace(" ", "_")
    user_id = payload.user_id

    logger.info(
        "[SITNIKS_API] Update status: stage=%s, user_id=%s, ig=%s",
        stage,
        user_id,
        payload.instagram_username,
    )

    try:
        if stage == "first_touch":
            result = await service.handle_first_touch(
                user_id=user_id,
                instagram_username=payload.instagram_username,
                telegram_username=payload.telegram_username,
            )
            return {
                "success": True,
                "stage": "first_touch",
                "result": result,
            }
        elif stage == "give_requisites":
            result = await service.handle_give_requisites(user_id=user_id)
            return {
                "success": True,
                "stage": "give_requisites",
                "result": result,
            }
        elif stage == "escalation":
            result = await service.handle_escalation(
                user_id=user_id,
                instagram_username=payload.instagram_username,
                telegram_username=payload.telegram_username,
            )
            return {
                "success": True,
                "stage": "escalation",
                "result": result,
            }
        else:
            return {
                "success": False,
                "error": f"Unknown stage: {stage}",
                "valid_stages": ["first_touch", "give_requisites", "escalation"],
            }
    except Exception as e:
        logger.exception("[SITNIKS_API] Error updating status: %s", e)
        return {
            "success": False,
            "error": str(e),
            "stage": stage,
        }

