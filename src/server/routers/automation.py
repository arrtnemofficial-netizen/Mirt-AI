"""Automation endpoints router.

Extracted from main.py to reduce God Object pattern.
Includes summarization, followups, and order creation endpoints.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from src.conf.config import settings
from src.server.dependencies import MessageStoreDep
from src.core.prompt_registry import get_snippet_by_header

logger = logging.getLogger(__name__)

def _get_msg(header: str, default: str = "") -> str:
    s = get_snippet_by_header(header)
    return s[0] if s else default

router = APIRouter(tags=["automation"])


def _generate_followup_text(current_state: str, last_product: str = "") -> str | None:
    """Generate follow-up message based on conversation state.

    Returns None if no follow-up needed (e.g., order completed).
    """
    followup_templates = {
        "STATE_1_DISCOVERY": _get_msg("AUTOMATION_FOLLOWUP_STATE_1"),
        "STATE_2_VISION": _get_msg("AUTOMATION_FOLLOWUP_STATE_2"),
        "STATE_3_SIZE_COLOR": _get_msg("AUTOMATION_FOLLOWUP_STATE_3"),
        # Special logic for state 4 below
        "STATE_5_PAYMENT_DELIVERY": _get_msg("AUTOMATION_FOLLOWUP_STATE_5"),
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

    if current_state == "STATE_4_OFFER":
        template = _get_msg("AUTOMATION_FOLLOWUP_STATE_4") or _get_msg("AUTOMATION_FOLLOWUP_STATE_4_DEFAULT")
        labels_json = get_snippet_by_header("VISION_LABELS")
        labels = json.loads(labels_json[0]) if labels_json else {}
        # Registry template: "\u0429\u0435 \u0440\u0430\u0437\u0434\u0443\u043c\u0443\u0454\u0442\u0435 \u043d\u0430\u0434 {product}?..."
        product_text = last_product if last_product else labels.get("order_genitive", "\u0437\u0430\u043c\u043e\u0432\u043b\u0435\u043d\u043d\u044f\u043c")
        return template.format(product=product_text)

    return followup_templates.get(current_state, _get_msg("AUTOMATION_FOLLOWUP_DEFAULT", "How can I help?"))


@router.post("/automation/mirt-summarize-prod-v1")
async def run_summarization(
    payload: dict[str, Any],
    message_store: MessageStoreDep,
) -> dict[str, Any]:
    """Summarize and prune old messages for a session.

    Called by ManyChat after 3 days of inactivity.
    Saves summary to users.summary and deletes messages from messages table.
    """
    from src.workers.dispatcher import dispatch_summarization

    session_id = payload.get("session_id")
    user_id = payload.get("user_id")

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    user_id_int = int(user_id) if user_id else None

    result = dispatch_summarization(session_id, user_id_int)

    if result.get("queued"):
        return {
            "session_id": session_id,
            "user_id": user_id,
            "status": "queued",
            "task_id": result.get("task_id"),
            "action": "remove_tags",
        }

    return {
        "session_id": session_id,
        "user_id": user_id,
        "summary": result.get("summary"),
        "action": "remove_tags",
        "status": "ok",
    }


@router.post("/automation/mirt-followups-prod-v1")
async def trigger_followups(
    payload: dict[str, Any],
    message_store: MessageStoreDep,
) -> dict[str, Any]:
    """Trigger follow-up messages for inactive sessions."""
    from src.workers.dispatcher import dispatch_followup

    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    result = dispatch_followup(session_id)

    if result.get("queued"):
        return {
            "session_id": session_id,
            "status": "queued",
            "task_id": result.get("task_id"),
        }

    return {
        "session_id": session_id,
        "followup_created": result.get("followup_created", False),
        "content": result.get("content"),
        "status": "ok",
    }


@router.post("/webhooks/manychat/followup")
async def manychat_followup(
    payload: dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
    message_store: MessageStoreDep = None,
) -> dict[str, Any]:
    """ManyChat follow-up endpoint called after Smart Delay."""
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    if verify_token and verify_token != x_manychat_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    subscriber = payload.get("subscriber") or payload.get("user") or {}
    user_id = str(subscriber.get("id") or subscriber.get("user_id") or "unknown")

    if user_id == "unknown":
        return {
            "needs_followup": False,
            "reason": "unknown_user",
        }

    custom_fields = payload.get("custom_fields") or {}
    current_state = custom_fields.get("ai_state", "STATE_0_INIT")
    last_product = custom_fields.get("last_product", "")

    followup_text = _generate_followup_text(current_state, last_product)
    needs_followup = followup_text is not None

    return {
        "needs_followup": needs_followup,
        "followup_text": followup_text or "",
        "current_state": current_state,
        "set_field_values": [
            {"field_name": "followup_sent", "field_value": "true" if needs_followup else "false"},
        ],
        "add_tag": ["followup_sent"] if needs_followup else [],
    }


@router.post("/webhooks/manychat/create-order")
async def manychat_create_order(
    payload: dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Create order in CRM from ManyChat data.

    IDEMPOTENT: Uses deterministic external_id based on user + product + price.
    """
    from src.integrations.crm.crmservice import CRMService
    from src.services.data.order_model import (
        build_missing_data_prompt,
        validate_order_data,
    )
    from src.services.infra.supabase_client import get_supabase_client

    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    if verify_token and verify_token != x_manychat_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    subscriber = payload.get("subscriber") or payload.get("user") or {}
    user_id = str(subscriber.get("id") or subscriber.get("user_id") or "unknown")
    custom_fields = payload.get("custom_fields") or {}

    import json
    labels_json = get_snippet_by_header("VISION_LABELS")
    labels = json.loads(labels_json[0]) if labels_json else {}

    full_name = custom_fields.get("client_name")
    phone = custom_fields.get("client_phone")
    city = custom_fields.get("client_city")
    nova_poshta = custom_fields.get("client_nova_poshta")
    product_name = custom_fields.get("last_product", labels.get("default_product", "\u0422\u043e\u0432\u0430\u0440"))
    order_sum = custom_fields.get("order_sum", "0")

    try:
        price = float(order_sum)
    except (ValueError, TypeError):
        price = 0.0

    products = [{"product_id": 1, "name": product_name, "price": price}] if product_name else []
    validation = validate_order_data(full_name, phone, city, nova_poshta, products)

    if not validation.can_submit_to_crm:
        prompt = build_missing_data_prompt(validation)
        return {
            "success": False,
            "needs_data": True,
            "missing_fields": validation.missing_fields,
            "prompt": prompt,
            "set_field_values": [
                {"field_name": "order_status", "field_value": "needs_data"},
            ],
        }

    # IDEMPOTENCY
    idempotency_data = f"{user_id}|{product_name.lower().strip()}|{int(price * 100)}"
    idempotency_hash = hashlib.sha256(idempotency_data.encode()).hexdigest()[:16]
    external_id = f"mc_{user_id}_{idempotency_hash}"

    logger.info(
        "[CREATE_ORDER] Idempotency key: %s (user=%s, product=%s, price=%s)",
        external_id,
        user_id,
        product_name[:20],
        price,
    )

    # CHECK FOR EXISTING ORDER
    supabase = get_supabase_client()
    if supabase:
        try:
            existing = (
                supabase.table("crm_orders")
                .select("id, crm_order_id, status, task_id")
                .eq("external_id", external_id)
                .limit(1)
                .execute()
            )
            if existing.data:
                order_data = existing.data[0]
                logger.info(
                    "[CREATE_ORDER] Duplicate detected, returning existing order: %s",
                    order_data.get("crm_order_id"),
                )
                return {
                    "success": True,
                    "order_id": order_data.get("crm_order_id"),
                    "status": order_data.get("status"),
                    "task_id": order_data.get("task_id"),
                    "message": _get_msg("AUTOMATION_ORDER_EXISTS", "Order exists"),
                    "duplicate": True,
                    "set_field_values": [
                        {
                            "field_name": "order_status",
                            "field_value": order_data.get("status", "created"),
                        },
                        {"field_name": "crm_external_id", "field_value": external_id},
                        {
                            "field_name": "crm_order_id",
                            "field_value": order_data.get("crm_order_id") or "",
                        },
                    ],
                    "add_tag": ["order_created"]
                    if order_data.get("status") == "created"
                    else ["order_queued"],
                }
        except Exception as e:
            logger.warning("[CREATE_ORDER] Failed to check for duplicate: %s", e)

    # Create order using CRMService
    try:
        crm_service = CRMService()

        order_data = {
            "customer": {
                "full_name": full_name,
                "phone": phone,
                "city": city,
                "nova_poshta_branch": nova_poshta,
                "manychat_id": user_id,
            },
            "items": [
                {
                    "product_id": 1,
                    "product_name": product_name,
                    "size": "",
                    "color": "",
                    "price": price,
                }
            ],
            "source": "manychat",
            "source_id": user_id,
        }

        result = await crm_service.create_order_with_persistence(
            session_id=user_id, external_id=external_id, order_data=order_data
        )

        if result.get("status") in ["queued", "created"]:
            logger.info(
                "[CREATE_ORDER] Order created successfully: %s",
                result.get("crm_order_id"),
            )

            return {
                "success": True,
                "order_id": result.get("crm_order_id"),
                "status": result.get("status"),
                "task_id": result.get("task_id"),
                "external_id": external_id,
                "message": _get_msg("AUTOMATION_ORDER_CREATED", "Order created"),
                "set_field_values": [
                    {"field_name": "order_status", "field_value": result.get("status")},
                    {"field_name": "crm_external_id", "field_value": external_id},
                    {"field_name": "crm_order_id", "field_value": result.get("crm_order_id") or ""},
                    {"field_name": "crm_task_id", "field_value": result.get("task_id") or ""},
                ],
                "add_tag": ["order_created"]
                if result.get("status") == "created"
                else ["order_queued"],
            }
        else:
            logger.error(
                "[CREATE_ORDER] Order creation failed: %s",
                result.get("error"),
            )
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "message": _get_msg("AUTOMATION_ORDER_FAILED", "Order creation failed"),
                "set_field_values": [
                    {"field_name": "order_status", "field_value": "failed"},
                ],
            }

    except Exception as e:
        logger.exception("[CREATE_ORDER] Failed to create order: %s", e)
        return {
            "success": False,
            "error": str(e),
            "message": _get_msg("AUTOMATION_ORDER_ERROR", "Error creating order"),
            "set_field_values": [
                {"field_name": "order_status", "field_value": "error"},
            ],
        }
