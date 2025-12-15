"""
Node Utilities - Common helpers for all nodes.
==============================================
"""

from __future__ import annotations

from typing import Any


# =============================================================================
# MESSAGE BUILDERS (DRY helpers)
# =============================================================================


def text_msg(content: str) -> dict[str, str]:
    """Create a text message dict for assistant response."""
    return {"role": "assistant", "type": "text", "content": content}


def image_msg(url: str) -> dict[str, str]:
    """Create an image message dict for assistant response."""
    return {"role": "assistant", "type": "image", "content": url}


def get_message_role(msg: Any) -> str:
    """Get role from message (handles both dict and LangChain objects)."""
    if isinstance(msg, dict):
        return msg.get("role", "")
    # LangChain: HumanMessage.type = "human", AIMessage.type = "ai"
    msg_type = getattr(msg, "type", "")
    if msg_type == "human":
        return "user"
    if msg_type == "ai":
        return "assistant"
    return msg_type


def has_assistant_reply(messages: list[Any]) -> bool:
    """Check if there's already an assistant reply in messages."""
    return any(get_message_role(m) in ("assistant", "ai") for m in messages)


# =============================================================================
# MESSAGE EXTRACTORS
# =============================================================================


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
        r'\bрост\s*(\d{2,3})\b',  # рост 147
        r'\bзріст\s*(\d{2,3})\b',  # зріст 120
        r'\bна\s*(\d{2,3})\s*(см)?\b',  # на 128, на 128 см
        r'\b(\d{2,3})\s*см\b',  # 120 см
        r'\b(\d{3})\b',  # просто 147 (тризначне)
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            height = int(match.group(1))
            if 80 <= height <= 180:  # Реальний діапазон
                return height
    return None


def get_size_and_price_for_height(height: int, prices_by_size: dict | None = None) -> tuple[str, int]:
    """
    Визначає розмір і ціну за зростом.
    
    Повертає: (size_label, price)
    """
    # Стандартні ціни для Мрія/Лагуна
    default_prices = {
        "80-92": 1590,
        "98-104": 1790,
        "110-116": 1990,
        "122-128": 2190,
        "134-140": 2290,
        "146-152": 2390,
        "158-164": 2390,
    }
    prices = prices_by_size or default_prices

    # Визначаємо розмір за зростом
    if height <= 92:
        return "80-92", prices.get("80-92", 1590)
    elif height <= 104:
        return "98-104", prices.get("98-104", 1790)
    elif height <= 116:
        return "110-116", prices.get("110-116", 1990)
    elif height <= 128:
        return "122-128", prices.get("122-128", 2190)
    elif height <= 140:
        return "134-140", prices.get("134-140", 2290)
    elif height <= 152:
        return "146-152", prices.get("146-152", 2390)
    else:
        return "158-164", prices.get("158-164", 2390)
