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
    - "98" -> 98 (двузначное число в диапазоне 80-99)
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
        r"^(\d{2})$",  # просто 98 (двузначное, только если это всё сообщение)
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            height = int(match.group(1))
            if 80 <= height <= 180:  # Реальний діапазон
                return height
    return None


def get_max_height_for_size(size_label: str) -> int:
    """
    Отримує максимальний зріст для розміру (фактично до якого зросту йде розмір).
    
    ЗАЛІЗОБЕТОННЕ ПРАВИЛО: На межах (120, 131, 143, 155) НЕ переходимо в більший розмір!
    
    Args:
        size_label: Розмір (наприклад, "146-152", "122-128")
    
    Returns:
        Максимальний зріст в см до якого йде розмір
    """
    size_max_height = {
        "80-92": 92,
        "98-104": 104,
        "110-116": 120,  # Включно до 120, не переходимо в 122-128!
        "122-128": 131,  # Включно до 131, не переходимо в 134-140!
        "134-140": 143,  # Включно до 143, не переходимо в 146-152!
        "146-152": 155,  # Включно до 155, не переходимо в 158-164!
        "158-164": 168,
    }
    return size_max_height.get(size_label, 168)


def get_size_recommendation_text(size_label: str) -> str:
    """
    Формує текст рекомендації розміру з вказівкою максимального зросту.
    
    Формат: "Вам чудово підійде наш розмір {size}, він іде фактично до зросту {max_height} см👌"
    
    Args:
        size_label: Розмір (наприклад, "146-152")
    
    Returns:
        Текст рекомендації
    """
    max_height = get_max_height_for_size(size_label)
    return f"Вам чудово підійде наш розмір {size_label}, він іде фактично до зросту {max_height} см👌"


def get_size_and_price_for_height(
    height: int, prices_by_size: dict | None = None
) -> tuple[str, int]:
    """
    Визначає розмір і ціну за зростом.
    
    ЗАЛІЗОБЕТОННЕ ПРАВИЛО: На межах (120, 131, 143, 155) НЕ переходимо в більший розмір!
    
    Лінійка відповідності:
    - 110-120 см включно → 110-116
    - 121-131 см включно → 122-128
    - 132-143 см включно → 134-140
    - 144-155 см включно → 146-152
    - 156-168 см включно → 158-164
    
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

    # ЗАЛІЗОБЕТОННА ЛОГІКА: точні діапазони з включними межами
    if height < 80:
        # Менше 80 см - найменший розмір
        return "80-92", prices.get("80-92", 1590)
    elif height <= 92:
        return "80-92", prices.get("80-92", 1590)
    elif height <= 104:
        return "98-104", prices.get("98-104", 1790)
    elif height <= 109:
        # 105-109 см - менше ніж 110, але більше ніж 104
        # Використовуємо найближчий менший розмір або 110-116 якщо немає проміжного
        return "98-104", prices.get("98-104", 1790)
    elif height <= 120:
        # 110-120 см включно → 110-116 (ВАЖЛИВО: 120 включно, не переходимо в 122-128!)
        return "110-116", prices.get("110-116", 1990)
    elif height <= 131:
        # 121-131 см включно → 122-128 (ВАЖЛИВО: 131 включно, не переходимо в 134-140!)
        return "122-128", prices.get("122-128", 2190)
    elif height <= 143:
        # 132-143 см включно → 134-140 (ВАЖЛИВО: 143 включно, не переходимо в 146-152!)
        return "134-140", prices.get("134-140", 2290)
    elif height <= 155:
        # 144-155 см включно → 146-152 (ВАЖЛИВО: 155 включно, не переходимо в 158-164!)
        return "146-152", prices.get("146-152", 2390)
    elif height <= 168:
        # 156-168 см включно → 158-164
        return "158-164", prices.get("158-164", 2390)
    else:
        # Більше 168 см - найбільший розмір
        return "158-164", prices.get("158-164", 2390)
