"""
Node Utilities - Common helpers for all nodes.
==============================================
"""

from __future__ import annotations

from typing import Any
from functools import lru_cache


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
<<<<<<< Updated upstream
=======


# =============================================================================
# SIZE/PRICE UTILITIES (shared by vision_node and agent_node)
# =============================================================================


def extract_height_from_text(text: str) -> int | None:
    """
    Витягує зріст з тексту повідомлення.

    Приклади:
    - "какая цена на рост 147" -> 147
    - "зріст 120" -> 120
    - "на 128 см" -> 128
    - "ціна" -> None
    """
    import re

    # Шукаємо числа 80-180 (реальний діапазон зросту дітей)
    patterns = [
        r"\bрост\s*(\d{2,3})\b",  # рост 147
        r"\bзріст\s*(\d{2,3})\b",  # зріст 120
        r"\bна\s*(\d{2,3})\s*(см)?\b",  # на 128, на 128 см
        r"\b(\d{2,3})\s*см\b",  # 120 см
        r"\b(\d{3})\b",  # просто 147 (тризначне)
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            height = int(match.group(1))
            if 80 <= height <= 180:  # Реальний діапазон
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
    Визначає розмір і ціну за зростом.
    
    Priority:
    1. Injected prices (from CatalogService check)
    2. Registry fallback (FALLBACK_PRICES_JSON)
    3. Config fallback
    """
    from src.conf.payment_config import DEFAULT_SUIT_PRICE
    prices = prices_by_size or _get_fallback_prices_from_registry()
    default_price = prices.get("80-92", DEFAULT_SUIT_PRICE)

    # Визначаємо розмір за зростом
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
>>>>>>> Stashed changes
