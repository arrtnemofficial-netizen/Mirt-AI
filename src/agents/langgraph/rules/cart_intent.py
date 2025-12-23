"""
Cart Intent Detection Rules.
============================
SSOT для детекції intent додавання товару до кошика.

Це централізоване джерело правил, які раніше були дубльовані в:
- src/agents/langgraph/nodes/agent.py (add_keywords logic)
"""

from __future__ import annotations


# =============================================================================
# ADD TO CART KEYWORDS (SSOT)
# =============================================================================

ADD_TO_CART_KEYWORDS: tuple[str, ...] = (
    # Ukrainian
    "ще",
    "додай",
    "добав",
    "також",
    "і ще",
    "ще один",
    "ще одну",
    "другий",
    "другу",
    # Russian variants
    "еще",
    "добавь",
    # Symbols
    "+",
)


# =============================================================================
# DETECTION FUNCTION
# =============================================================================

def detect_add_to_cart(user_text: str) -> bool:
    """
    Detect if user wants to add another product to cart.
    
    Args:
        user_text: User message text (will be lowercased)
    
    Returns:
        True if add-to-cart intent is detected, False otherwise
    
    Examples:
        >>> detect_add_to_cart("Ще один товар")
        True
        >>> detect_add_to_cart("Додай ще")
        True
        >>> detect_add_to_cart("Також цей")
        True
        >>> detect_add_to_cart("Хочу купити")
        False
    """
    if not user_text:
        return False
    
    user_text_lower = user_text.lower().strip()
    
    # Check if any add-to-cart keyword is present
    for keyword in ADD_TO_CART_KEYWORDS:
        if keyword in user_text_lower:
            return True
    
    return False

