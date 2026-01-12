
"""
Color Handler.
==============
Responsible for "Show me colors" requests.
Handles:
1. Detecting color requests (universal).
2. Fetching photos from product helper.
3. Pagination (Show More).
4. Constructing image-only messages.
"""

import logging
from contextlib import suppress
from typing import Any

from src.agents.langgraph.rules.color_request import (
    detect_color_show_request,
    get_current_color_for_exclusion,
    get_product_name_for_color_show,
)
from src.agents.langgraph.nodes.helpers.vision.product_colors import (
    get_color_photos_for_upsell,
)
from src.services.observability import log_agent_step

logger = logging.getLogger(__name__)


def handle_color_request(
    state: dict[str, Any],
    user_message: str,
) -> dict[str, Any] | None:
    """
    Handle color show request (universal for any state).

    Args:
        state: Current conversation state.
        user_message: User's latest message.

    Returns:
        State update dict if handled, None otherwise.
    """
    current_state = state.get("current_state", "UNKNOWN")
    
    # 1. Detection
    is_color_request = detect_color_show_request(user_message)
    is_show_more = (
        user_message.lower().strip() in ["показати решту", "покажи решту", "так", "да", "ок"]
        and state.get("metadata", {}).get("color_gallery_offset") is not None
    )

    if not (is_color_request or is_show_more):
        return None

    # 2. Context Resolution
    product_name = get_product_name_for_color_show(state)
    if not product_name:
        return None

    exclude_color = get_current_color_for_exclusion(state)

    # 3. Pagination Logic
    if is_show_more:
        metadata = state.get("metadata", {})
        offset = metadata.get("color_gallery_offset", 0)
        # Restore context from metadata
        if metadata.get("color_gallery_product"):
            product_name = metadata.get("color_gallery_product")
        if metadata.get("color_gallery_exclude"):
            exclude_color = metadata.get("color_gallery_exclude")
    else:
        offset = 0

    # 4. Fetch Photos
    color_photos, has_more = get_color_photos_for_upsell(
        product_name=product_name,
        exclude_color=exclude_color,
        max_photos=4,
        offset=offset,
    )

    if not color_photos:
        return None

    # 5. Build Response
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    trace_id = state.get("trace_id", "")
    messages = []

    # Images first
    for color_photo in color_photos:
        photo_url = color_photo.get("photo_url")
        if photo_url:
            messages.append({"type": "image", "content": photo_url})

    # "Show more" limit
    metadata_update = state.get("metadata", {}).copy()
    
    if has_more:
        messages.append({
            "type": "text",
            "content": "Показати решту кольорів?",
        })
        # Save cursor
        metadata_update["color_gallery_offset"] = offset + len(color_photos)
        metadata_update["color_gallery_product"] = product_name
        if exclude_color:
            metadata_update["color_gallery_exclude"] = exclude_color
    else:
        # Clear cursor
        metadata_update.pop("color_gallery_offset", None)
        metadata_update.pop("color_gallery_product", None)
        metadata_update.pop("color_gallery_exclude", None)

    # Agent Response Payload
    agent_response_payload = {
        "event": "simple_answer",
        "messages": messages,
        "products": state.get("selected_products", []) or [],
        "metadata": {
            "session_id": session_id,
            "current_state": current_state,
            "intent": "COLOR_HELP",
            "escalation_level": "NONE",
        },
    }

    # State Update
    metadata_update["current_state"] = current_state
    metadata_update["intent"] = "COLOR_HELP"

    assistant_messages = []
    for msg in messages:
        if msg["type"] == "text":
            assistant_messages.append({
                "role": "assistant",
                "content": msg["content"],
            })
        elif msg["type"] == "image":
            assistant_messages.append({
                "role": "assistant",
                "type": "image",
                "content": msg["content"],
            })

    # 6. Observability
    with suppress(Exception):
        log_agent_step(
            session_id=session_id,
            state=current_state,
            intent="COLOR_HELP",
            event="color_gallery_shown",
            latency_ms=0.0,
            extra={
                "trace_id": trace_id,
                "product_name": product_name,
                "colors_shown": len(color_photos),
                "has_more": has_more,
                "offset": offset,
            },
        )

    return {
        "current_state": current_state,
        "detected_intent": "COLOR_HELP",
        "dialog_phase": state.get("dialog_phase", "WAITING_FOR_COLOR"),
        "messages": assistant_messages,
        "metadata": metadata_update,
        "selected_products": state.get("selected_products", []) or [],
        "should_escalate": False,
        "escalation_reason": None,
        "step_number": state.get("step_number", 0) + 1,
        "last_error": None,
        "agent_response": agent_response_payload,
    }
