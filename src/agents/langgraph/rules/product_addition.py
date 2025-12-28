"""
Product Addition Intent Detection Rules.
========================================
SSOT для детекції наміру додати товар до замовлення.

Використовується для розрізнення між:
- Payment proof (скрін оплати)
- Product addition (фото товару для додавання до замовлення)
"""

from __future__ import annotations


# =============================================================================
# PRODUCT ADDITION KEYWORDS (SSOT)
# =============================================================================

PRODUCT_ADDITION_KEYWORDS: tuple[str, ...] = (
    # Ukrainian patterns
    "додати",
    "додати ще",
    "можна ще додати",
    "хочу ще",
    "хочу додати",
    "ще один",
    "ще одна",
    "ще одне",
    "цій костюм",
    "цей костюм",
    "цю сукню",
    "цю сукня",
    "цей товар",
    "цей товар на фото",
    "що на фото",
    "який на фото",
    "костюм",
    "сукня",
    "тренч",
    "хочу цей",
    "хочу цю",
    "хочу цей костюм",
    "хочу цю сукню",
    "додай",
    "додайте",
    "додам",
    # Russian patterns
    "добавить",
    "добавить еще",
    "можно еще добавить",
    "хочу еще",
    "хочу добавить",
    "еще один",
    "еще одна",
    "еще одно",
    "этот костюм",
    "эту сукню",
    "этот товар",
    "этот товар на фото",
    "что на фото",
    "какой на фото",
    "хочу этот",
    "хочу эту",
    "хочу этот костюм",
    "хочу эту сукню",
    "добавь",
    "добавьте",
)


# =============================================================================
# DETECTION FUNCTION
# =============================================================================

def detect_product_addition_intent(user_text: str) -> bool:
    """
    Detect if user message indicates intent to add a product to order.
    
    Args:
        user_text: User message text (will be lowercased)
    
    Returns:
        True if product addition intent is detected, False otherwise
    
    Examples:
        >>> detect_product_addition_intent("А можна ще додати")
        True
        >>> detect_product_addition_intent("Цей костюм")
        True
        >>> detect_product_addition_intent("Оплатила")
        False
        >>> detect_product_addition_intent("")
        False
    """
    if not user_text:
        return False
    
    user_text_lower = user_text.lower().strip()
    
    # Check for product addition keywords
    for keyword in PRODUCT_ADDITION_KEYWORDS:
        if keyword in user_text_lower:
            return True
    
    return False

