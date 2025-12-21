"""CRM integration routers.

Combines Snitkix Webhooks and Sitniks API endpoints.
Extracted from main.py and consolidated to reduce file clutter.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.conf.config import settings
from src.server.models.requests import SitniksUpdateRequest

logger = logging.getLogger(__name__)

# =============================================================================
# SNITKIX CRM WEBHOOKS
# =============================================================================

snitkix_router = APIRouter(prefix="/webhooks/snitkix", tags=["crm", "snitkix"])


@snitkix_router.post("/order-status")
async def snitkix_order_status_webhook(request: Request) -> JSONResponse:
    """Handle order status updates from Snitkix CRM."""
    from src.integrations.crm.webhooks import snitkix_order_status_webhook as webhook_handler

    return await webhook_handler(request)


@snitkix_router.post("/payment")
async def snitkix_payment_webhook(request: Request) -> JSONResponse:
    """Handle payment confirmation from Snitkix CRM."""
    from src.integrations.crm.webhooks import snitkix_payment_webhook as webhook_handler

    return await webhook_handler(request)


@snitkix_router.post("/inventory")
async def snitkix_inventory_webhook(request: Request) -> JSONResponse:
    """Handle inventory updates from Snitkix CRM."""
    from src.integrations.crm.webhooks import snitkix_inventory_webhook as webhook_handler

    return await webhook_handler(request)


# =============================================================================
# SITNIKS API (Integration for ManyChat/JS)
# =============================================================================

sitniks_router = APIRouter(prefix="/api/v1/sitniks", tags=["crm", "sitniks"])


def _verify_auth_token(
    x_api_key: str | None,
    authorization: str | None,
) -> None:
    """Verify API token from headers."""
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    inbound_token = x_api_key
    if not inbound_token and authorization:
        auth_value = authorization.strip()
        if auth_value.lower().startswith("bearer "):
            inbound_token = auth_value[7:].strip()
        else:
            inbound_token = auth_value

    if verify_token and verify_token != inbound_token:
        raise HTTPException(status_code=401, detail="Invalid API token")


@sitniks_router.post("/update-status")
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
    """
    from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service

    _verify_auth_token(x_api_key, authorization)

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
                "success": result.get("success", False),
                "stage": stage,
                "chat_id": result.get("chat_id"),
                "status_set": result.get("status_set", False),
                "manager_assigned": result.get("manager_assigned", False),
                "error": result.get("error"),
            }

        elif stage in ("give_requisites", "invoice", "invoice_sent"):
            success = await service.handle_invoice_sent(user_id)
            return {
                "success": success,
                "stage": "give_requisites",
            }

        elif stage == "escalation":
            result = await service.handle_escalation(user_id)
            return {
                "success": result.get("success", False),
                "stage": stage,
                "chat_id": result.get("chat_id"),
                "status_set": result.get("status_set", False),
                "manager_assigned": result.get("manager_assigned", False),
            }

        else:
            return {
                "success": False,
                "error": f"Unknown stage: {stage}. Valid: first_touch, give_requisites, escalation",
            }

    except Exception as e:
        logger.exception("[SITNIKS_API] Error: %s", e)
        return {
            "success": False,
            "error": str(e),
            "stage": stage,
        }
