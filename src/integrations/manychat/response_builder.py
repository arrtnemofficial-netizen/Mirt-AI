from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from src.core.registry_keys import SystemKeys
from src.core.prompt_registry import load_yaml_from_registry
from src.services.client_data_parser import ClientData
from src.services.infra.renderer import render_agent_response_text

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_manychat_config() -> dict[str, Any]:
    data = load_yaml_from_registry(SystemKeys.MANYCHAT.value)
    return data if isinstance(data, dict) else {}


# Custom fields
FIELD_AI_STATE = "ai_state"
FIELD_AI_INTENT = "ai_intent"
FIELD_LAST_PRODUCT = "last_product"
FIELD_ORDER_SUM = "order_sum"
FIELD_CLIENT_NAME = "client_name"
FIELD_CLIENT_PHONE = "client_phone"
FIELD_CLIENT_CITY = "client_city"
FIELD_CLIENT_NP = "client_nova_poshta"

# Tags
TAG_AI_RESPONDED = "ai_responded"
TAG_NEEDS_HUMAN = "needs_human"
TAG_ORDER_STARTED = "order_started"
TAG_ORDER_PAID = "order_paid"


def build_manychat_messages(agent_response, *, include_product_images: bool = True) -> list[dict[str, Any]]:
    """Build ManyChat message list from AgentResponse."""
    text_chunks = render_agent_response_text(agent_response)
    messages: list[dict[str, Any]] = [{"type": "text", "text": chunk} for chunk in text_chunks]

    if include_product_images:
        for product in agent_response.products:
            if product.photo_url:
                messages.append(
                    {
                        "type": "image",
                        "url": product.photo_url,
                        "caption": f"{product.name} - {product.price} грн",
                    }
                )

    return messages


def build_manychat_field_values(
    agent_response,
    client_data: ClientData | None = None,
) -> list[dict[str, str]]:
    """Build Custom Field values from AgentResponse and parsed client data."""
    fields = [
        {"field_name": FIELD_AI_STATE, "field_value": agent_response.metadata.current_state},
        {"field_name": FIELD_AI_INTENT, "field_value": agent_response.metadata.intent},
    ]

    if agent_response.products:
        last_product = agent_response.products[-1]
        fields.append({"field_name": FIELD_LAST_PRODUCT, "field_value": last_product.name})
        if last_product.price:
            fields.append({"field_name": FIELD_ORDER_SUM, "field_value": str(last_product.price)})

    if client_data:
        if client_data.full_name:
            fields.append({"field_name": FIELD_CLIENT_NAME, "field_value": client_data.full_name})
        if client_data.phone:
            fields.append({"field_name": FIELD_CLIENT_PHONE, "field_value": client_data.phone})
        if client_data.city:
            fields.append({"field_name": FIELD_CLIENT_CITY, "field_value": client_data.city})
        if client_data.nova_poshta:
            fields.append({"field_name": FIELD_CLIENT_NP, "field_value": client_data.nova_poshta})

    return fields


def build_manychat_tags(agent_response) -> tuple[list[str], list[str]]:
    """Build tags to add/remove based on AgentResponse."""
    add_tags = [TAG_AI_RESPONDED]
    remove_tags: list[str] = []

    if agent_response.metadata.escalation_level != "NONE":
        add_tags.append(TAG_NEEDS_HUMAN)
    else:
        remove_tags.append(TAG_NEEDS_HUMAN)

    current_state = agent_response.metadata.current_state
    if current_state in ("STATE_5_PAYMENT_DELIVERY", "STATE_6_UPSELL"):
        add_tags.append(TAG_ORDER_STARTED)

    if current_state == "STATE_7_END" and agent_response.event == "escalation":
        if agent_response.escalation and "ORDER_CONFIRMED" in (agent_response.escalation.reason or ""):
            add_tags.append(TAG_ORDER_PAID)

    return add_tags, remove_tags


def build_manychat_quick_replies(agent_response) -> list[dict[str, str]]:
    """Build quick replies based on config."""
    config = _get_manychat_config()
    quick = config.get("quick_replies", {}) if isinstance(config, dict) else {}
    current_state = agent_response.metadata.current_state
    replies: list[dict[str, str]] = []

    def _map_captions(key: str) -> list[dict[str, str]]:
        captions = quick.get(key, [])
        return [{"type": "text", "caption": c} for c in captions]

    if current_state in ("STATE_0_INIT", "STATE_1_DISCOVERY"):
        replies = _map_captions("state_0_1")
    elif current_state == "STATE_3_SIZE_COLOR":
        replies = _map_captions("state_3")
    elif current_state == "STATE_4_OFFER":
        replies = _map_captions("state_4")
    elif current_state == "STATE_5_PAYMENT_DELIVERY":
        replies = _map_captions("state_5")

    if agent_response.metadata.escalation_level != "NONE":
        replies = _map_captions("escalation")

    return replies


def build_manychat_response(
    agent_response,
    *,
    client_data: ClientData | None = None,
    include_product_images: bool = True,
    quick_replies: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build full ManyChat v2 response envelope from AgentResponse."""
    messages = build_manychat_messages(agent_response, include_product_images=include_product_images)
    field_values = build_manychat_field_values(agent_response, client_data)
    add_tags, remove_tags = build_manychat_tags(agent_response)
    quick_replies = quick_replies if quick_replies is not None else build_manychat_quick_replies(agent_response)

    response: dict[str, Any] = {
        "version": "v2",
        "content": {
            "messages": messages,
            "actions": [],
            "quick_replies": quick_replies,
        },
        "set_field_values": field_values,
        "add_tag": add_tags,
        "remove_tag": remove_tags,
    }

    response["_debug"] = {
        "event": agent_response.event,
        "current_state": agent_response.metadata.current_state,
        "intent": agent_response.metadata.intent,
        "escalation": agent_response.escalation.model_dump() if agent_response.escalation else None,
    }

    return response


def build_text_response(text: str) -> dict[str, Any]:
    """Utility for plain-text responses (fallback/rate-limit)."""
    safe_text = text or ""
    return {
        "version": "v2",
        "content": {"messages": [{"type": "text", "text": safe_text}], "actions": [], "quick_replies": []},
        "set_field_values": [],
        "add_tag": [],
        "remove_tag": [],
    }
