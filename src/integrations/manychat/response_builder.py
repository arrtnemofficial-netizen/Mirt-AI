from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from src.core.models import AgentResponse

from .constants import (
    FIELD_AI_INTENT,
    FIELD_AI_STATE,
    FIELD_LAST_PRODUCT,
    FIELD_ORDER_SUM,
    TAG_AI_RESPONDED,
    TAG_NEEDS_HUMAN,
    TAG_ORDER_PAID,
    TAG_ORDER_STARTED,
)


def build_manychat_messages(
    agent_response: AgentResponse,
    *,
    include_product_images: bool,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for msg in agent_response.messages:
        if msg.type == "text":
            # Split into separate bubbles by blank lines to simulate human-style messaging.
            parts = [p.strip() for p in str(msg.content).split("\n\n") if p and p.strip()]
            if not parts:
                continue
            for part in parts:
                messages.append({"type": "text", "text": part})
        elif msg.type == "image":
            url = str(msg.content or "").strip()
            if url:
                messages.append({"type": "image", "url": url})

    if include_product_images:
        existing_urls = {m.get("url") for m in messages if m.get("type") == "image"}
        for product in agent_response.products:
            if product.photo_url:
                if product.photo_url not in existing_urls:
                    messages.append({"type": "image", "url": product.photo_url})

    return messages


def build_manychat_field_values(agent_response: AgentResponse) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = [
        {"field_name": FIELD_AI_STATE, "field_value": agent_response.metadata.current_state},
        {"field_name": FIELD_AI_INTENT, "field_value": agent_response.metadata.intent},
    ]

    if agent_response.products:
        last_product = agent_response.products[-1]
        fields.append({"field_name": FIELD_LAST_PRODUCT, "field_value": last_product.name})
        if last_product.price:
            fields.append({"field_name": FIELD_ORDER_SUM, "field_value": last_product.price})

    return fields


def build_manychat_tags(agent_response: AgentResponse) -> tuple[list[str], list[str]]:
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
        if agent_response.escalation and "ORDER_CONFIRMED" in (
            agent_response.escalation.reason or ""
        ):
            add_tags.append(TAG_ORDER_PAID)

    return add_tags, remove_tags


def build_manychat_v2_response(
    agent_response: AgentResponse,
    *,
    include_product_images: bool,
    quick_replies: list[dict[str, Any]] | None,
    include_debug: bool,
) -> dict[str, Any]:
    messages = build_manychat_messages(
        agent_response,
        include_product_images=include_product_images,
    )

    field_values = build_manychat_field_values(agent_response)
    tags_to_add, tags_to_remove = build_manychat_tags(agent_response)

    response: dict[str, Any] = {
        "version": "v2",
        "content": {
            "messages": messages,
            "actions": [],
            "quick_replies": quick_replies or [],
        },
        "set_field_values": field_values,
        "add_tag": tags_to_add,
        "remove_tag": tags_to_remove,
    }

    if include_debug:
        response["_debug"] = {
            "event": agent_response.event,
            "current_state": agent_response.metadata.current_state,
            "intent": agent_response.metadata.intent,
            "escalation": agent_response.escalation.model_dump()
            if agent_response.escalation
            else None,
        }

    return response
