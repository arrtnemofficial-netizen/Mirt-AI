"""
Offer Transition Detection Rules.
=================================
SSOT для детекції переходу з offer до payment (delivery request).

Це централізоване джерело правил, які раніше були дубльовані в:
- src/agents/langgraph/nodes/offer.py (detect_delivery_request logic)
"""

from __future__ import annotations


# =============================================================================
# DELIVERY REQUEST KEYWORDS (SSOT)
# =============================================================================

DELIVERY_REQUEST_KEYWORDS: tuple[str, ...] = (
    # Location keywords
    "місто",
    "відділення",
    "нової пошти",
    "нова пошта",
    # Personal data keywords
    "піб",
    "прізвище",
    "ім'я",
    "імʼя",  # Alternative apostrophe
    "телефон",
    "номер телефону",
    # Action keywords (requesting data)
    "надішліть",
    "напишіть",
    "вкажіть",
    "введіть",
    # Order keywords
    "бронюємо",
    "зарезервувати",
    "оформити",
    "замовлення",
)


# =============================================================================
# DETECTION FUNCTION
# =============================================================================

def detect_delivery_request(text: str) -> bool:
    """
    Detect if text asks for delivery data (місто, відділення, ПІБ, телефон).
    
    Args:
        text: Text to check (will be lowercased)
    
    Returns:
        True if delivery request is detected, False otherwise
    
    Examples:
        >>> detect_delivery_request("Напишіть місто та відділення Нової Пошти")
        True
        >>> detect_delivery_request("Вкажіть ПІБ та телефон")
        True
        >>> detect_delivery_request("Чудовий товар!")
        False
    """
    if not text:
        return False
    
    text_lower = text.lower().strip()
    
    # Check if any delivery keyword is present
    for keyword in DELIVERY_REQUEST_KEYWORDS:
        if keyword in text_lower:
            return True
    
    return False

