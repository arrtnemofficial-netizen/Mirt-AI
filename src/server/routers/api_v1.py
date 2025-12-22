"""API v1 router for external integrations.

This router handles /api/v1/* endpoints for external systems like ManyChat, n8n, etc.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.conf.config import settings
from src.core.logging import log_event, safe_preview
from src.integrations.manychat.async_service import get_manychat_async_service
from src.server.dependencies import get_session_store
from src.server.models.requests import ApiV1MessageRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["api", "v1"])


@router.post("/messages", status_code=202)
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
    # #region agent log
    raw_body = await request.body()
    log_event(
        logger,
        event="api_v1_payload_received",
        text_len=len(raw_body or b""),
        text_preview=safe_preview(raw_body.decode("utf-8", errors="replace"), 200),
    )
    # #endregion

    try:
        raw_json = json.loads(raw_body)
        logger.debug("[API_V1] RAW keys=%s", list(raw_json.keys()))
    except json.JSONDecodeError as e:
        log_event(
            logger,
            event="api_v1_payload_parsed",
            level="warning",
            root_cause="INVALID_JSON",
            error=safe_preview(str(e), 200),
        )
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    try:
        payload = ApiV1MessageRequest.model_validate(raw_json)
        # #region agent log
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
        # #endregion
    except Exception as e:
        logger.error("[API_V1] ❌ Pydantic validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    # === STEP 3: Auth check ===
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    inbound_token = x_api_key
    if not inbound_token and authorization:
        auth_value = authorization.strip()
        if auth_value.lower().startswith("bearer "):
            inbound_token = auth_value[7:].strip()
        else:
            inbound_token = auth_value

    if verify_token and verify_token != inbound_token:
        # #region agent log
        logger.warning(
            "[API_V1] 🔒 Auth failed: expected=%s, got=%s",
            verify_token[:10] if verify_token else None,
            inbound_token[:10] if inbound_token else None,
        )
        # #endregion
        raise HTTPException(status_code=401, detail="Invalid API token")

    # === STEP 4: Schedule background processing ===
    store = get_session_store()
    service = get_manychat_async_service(store)

    user_id = str(payload.client_id)
    channel = payload.type or "instagram"

    trace_id = str(uuid.uuid4())

    # #region agent log
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
    # #endregion

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

