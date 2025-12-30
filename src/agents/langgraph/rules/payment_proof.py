"""
Payment Proof Detection Rules.
==============================
SSOT для детекції payment proof (скрін, квитанція, оплата).

Це централізоване джерело правил, які раніше були дубльовані в:
- src/agents/langgraph/state_prompts.py (get_payment_sub_phase)
- src/agents/langgraph/nodes/payment.py (_handle_delivery_data)
"""

from __future__ import annotations

from src.agents.langgraph.rules.product_addition import detect_product_addition_intent


# =============================================================================
# PAYMENT PROOF KEYWORDS (SSOT)
# =============================================================================

PAYMENT_PROOF_KEYWORDS: tuple[str, ...] = (
    # Ukrainian
    "оплатила",
    "оплатив",
    "оплачено",
    "переказала",
    "переказав",
    "переказано",
    "відправила скрін",
    "відправив скрін",
    "скрін",
    "скрин",  # Russian variant
    "квитанцію",
    "квитанц",  # Partial match
    "доказ оплати",
    "готово",  # Generic confirmation
)

# Keywords that indicate payment proof ONLY if combined with image/URL
PAYMENT_PROOF_WEAK_KEYWORDS: tuple[str, ...] = (
    "оплатила",
    "оплатив",
    "готово",
)


# =============================================================================
# DETECTION FUNCTION
# =============================================================================

def detect_payment_proof(
    user_text: str,
    has_image: bool = False,
    has_url: bool = False,
) -> bool:
    """
    Detect if user message contains payment proof.
    
    Args:
        user_text: User message text (will be lowercased)
        has_image: Whether message contains an image
        has_url: Whether message contains a URL (http/https)
    
    Returns:
        True if payment proof is detected, False otherwise
    
    Detection logic:
    1. Image presence → always proof (likely screenshot)
    2. URL presence → proof (likely screenshot link)
    3. Strong keywords (скрін, квитанцію, доказ оплати) → always proof
    4. Weak keywords (оплатила, готово) → proof only if has_image or has_url
    
    Examples:
        >>> detect_payment_proof("Оплатила", has_image=True)
        True
        >>> detect_payment_proof("Оплатила")  # No image/URL
        False
        >>> detect_payment_proof("Надіслав скрін")
        True
        >>> detect_payment_proof("https://example.com/screenshot.jpg")
        True
        >>> detect_payment_proof("", has_image=True)  # Empty text but has image
        True
    """
    # Empty text without image/URL → not proof
    if not user_text and not has_image and not has_url:
        return False

    user_text_lower = user_text.lower().strip() if user_text else ""

    # CRITICAL: Check for product addition intent FIRST
    # If user wants to add a product, this is NOT payment proof
    if user_text and detect_product_addition_intent(user_text):
        return False

    # URL presence → proof (likely screenshot link)
    if has_url or (user_text_lower and ("http://" in user_text_lower or "https://" in user_text_lower)):
        return True

    # Strong keywords → always proof (check before image check)
    if user_text_lower:
        for keyword in PAYMENT_PROOF_KEYWORDS:
            if keyword in user_text_lower:
                # Check if it's a weak keyword that needs image/URL
                if keyword in PAYMENT_PROOF_WEAK_KEYWORDS:
                    # Weak keyword → proof only if has_image or has_url
                    if has_image or has_url:
                        return True
                    # Otherwise, continue checking other keywords
                else:
                    # Strong keyword → always proof
                    return True

    # Image presence → proof (likely screenshot)
    # BUT: Only if text doesn't indicate product addition (already checked above)
    # КРИТИЧНО: Если текст содержит данные доставки (ПІБ, телефон, місто, НП) - это НЕ payment proof!
    # Это фото товара, которое пользователь отправил вместе с данными
    if has_image:
        # Проверяем наличие данных доставки в тексте
        delivery_data_keywords = [
            "немченко", "юрий", "володимирович",  # ПІБ
            "+380", "095", "050",  # Телефон
            "киев", "київ", "харьков", "одесса",  # Місто
            "нп", "відділення", "поштомат", "123", "58",  # НП
        ]
        has_delivery_data = any(kw in user_text_lower for kw in delivery_data_keywords)
        
        # Если есть данные доставки - это НЕ payment proof, это фото товара
        if has_delivery_data:
            return False
        
        # Если текст пустой или не содержит данных доставки - проверяем дальше
        if not user_text_lower:
            # Пустой текст + фото - возможно payment proof, но нужно проверить контекст
            # В STATE_5 если нет данных доставки - это скорее всего фото товара
            return False  # Без текста не детектируем как payment proof в STATE_5
        
        # Если текст есть, но нет данных доставки и нет product addition - возможно payment proof
        # Но только если есть keywords оплаты
        has_payment_keywords = any(kw in user_text_lower for kw in PAYMENT_PROOF_KEYWORDS)
        if has_payment_keywords:
            return True
        
        # Если нет keywords оплаты - не детектируем как payment proof
        return False

    return False

