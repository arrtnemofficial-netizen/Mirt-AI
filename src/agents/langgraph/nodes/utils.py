"""
Node Utilities - Common helpers for all nodes.
==============================================
"""

from __future__ import annotations

from typing import Any
from functools import lru_cache

__all__ = [
    "extract_user_message",
    "extract_assistant_message",
    "extract_height_from_text",
    "get_size_and_price_for_height",
    "text_msg",
    "image_msg",
]


def extract_user_message(messages: list[Any]) -> str:
    """
    Extract the latest user message from messages list.

    Handles both:
    - Dict format: {"role": "user", "content": "..."}
    - LangChain Message objects: HumanMessage, AIMessage, etc.

    The add_messages reducer in LangGraph converts dicts to Message objects,
    so we need to handle both formats.

    Args:
        messages: List of messages (dict or Message objects)

    Returns:
        Content of the latest user message, or empty string if not found
    """
    for msg in reversed(messages):
        # Handle dict format
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                return msg.get("content", "")
        else:
            # LangChain Message object (HumanMessage, AIMessage, etc.)
            # Check by type attribute or class name
            msg_type = getattr(msg, "type", None)
            class_name = msg.__class__.__name__

            if msg_type == "human" or class_name == "HumanMessage":
                return getattr(msg, "content", "")

    return ""


def extract_assistant_message(messages: list[Any]) -> str:
    """
    Extract the latest assistant message from messages list.

    Args:
        messages: List of messages (dict or Message objects)

    Returns:
        Content of the latest assistant message, or empty string if not found
    """
    for msg in reversed(messages):
        if isinstance(msg, dict):
            if msg.get("role") == "assistant":
                return msg.get("content", "")
        else:
            msg_type = getattr(msg, "type", None)
            class_name = msg.__class__.__name__

            if msg_type == "ai" or class_name == "AIMessage":
                return getattr(msg, "content", "")

    return ""


# =============================================================================
# SIZE/PRICE UTILITIES (shared by vision_node and agent_node)
# =============================================================================


def extract_height_from_text(text: str) -> int | None:
    """
    Extract height from a user message.

    Examples:
    - "price for height 147" -> 147
    - "height 120" -> 120
    - "at 128 cm" -> 128
    - "price" -> None
    """
    import re

    # Match 80-180 range (typical child height range).
    patterns = [
        r"\b\u0440\u043e\u0441\u0442\s*(\d{2,3})\b",  # "height 147"
        r"\b\u0437\u0440\u0456\u0441\u0442\s*(\d{2,3})\b",  # "height 120"
        r"\b\u043d\u0430\s*(\d{2,3})\s*(\u0441\u043c)?\b",  # "at 128 cm"
        r"\b(\d{2,3})\s*\u0441\u043c\b",  # "120 cm"
        r"\b(\d{3})\b",  # "147"
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            height = int(match.group(1))
            if 80 <= height <= 180:
                return height
    return None


@lru_cache(maxsize=1)
def _get_fallback_prices_from_registry() -> dict[str, int]:
    """Load default prices from registry JSON."""
    from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header
    import json
    from src.conf.payment_config import SUIT_PRICE_BY_SIZE

    # 1. Try Registry (SSOT)
    try:
        bubbles = get_snippet_by_header("FALLBACK_PRICES_JSON")
        if bubbles:
            data = json.loads(bubbles[0])
            if isinstance(data, dict):
                return {k: int(v) for k, v in data.items()}
    except Exception:
        pass

    # 2. Fallback to Config (Code Default)
    # This ensures we don't crash if registry is broken
    return SUIT_PRICE_BY_SIZE


def get_size_and_price_for_height(
    height: int, prices_by_size: dict | None = None
) -> tuple[str, int]:
    """
    Determine size and price by height.

    Priority:
    1. Injected prices (from CatalogService check)
    2. Registry fallback (FALLBACK_PRICES_JSON)
    3. Config fallback
    """
    from src.conf.payment_config import DEFAULT_SUIT_PRICE
    prices = prices_by_size or _get_fallback_prices_from_registry()
    default_price = prices.get("80-92", DEFAULT_SUIT_PRICE)

    # Determine size by height.
    if height <= 92:
        size = "80-92"
    elif height <= 104:
        size = "98-104"
    elif height <= 116:
        size = "110-116"
    elif height <= 128:
        size = "122-128"
    elif height <= 140:
        size = "134-140"
    elif height <= 152:
        size = "146-152"
    else:
        size = "158-164"

    return size, prices.get(size, default_price)


def text_msg(text: str, *, message_type: str = "text", **metadata: Any) -> dict[str, Any]:
    """
    Build LangGraph-compatible text bubble.

    Args:
        text: Body of the message.
        message_type: Optional type (defaults to "text").
        metadata: Extra fields to attach.

    Returns:
        Dict representing a message ready for agent_response/messages list.
    """
    return {
        "type": message_type,
        "text": text,
        **metadata,
    }


def image_msg(url: str, *, caption: str | None = None, **metadata: Any) -> dict[str, Any]:
    """
    Build LangGraph-compatible image bubble.

    Args:
        url: Link to the image.
        caption: Optional caption text.
        metadata: Additional fields.
    """
    payload = {
        "type": "image",
        "image_url": url,
        **metadata,
    }
    if caption:
        payload["caption"] = caption
    return payload
