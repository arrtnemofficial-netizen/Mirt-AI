"""
FSM Facts - Вычисление фактов из состояния и событий.
======================================================

Этот модуль извлекает "факты" из состояния и событий, которые используются
для принятия решений в reducer. Факты - это чистые функции без side effects.

КЛЮЧЕВАЯ ИДЕЯ:
- Keyword detection и другая "детекция" вынесена сюда
- Reducer получает готовые факты, а не делает детекцию сам
- Это позволяет тестировать факты отдельно от reducer
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_facts(
    state: dict[str, Any],
    intent: str,
    user_message: str | None = None,
) -> dict[str, Any]:
    """
    Вычислить все факты из состояния и события.
    
    Returns:
        dict с ключами:
        - has_products: bool
        - has_size: bool
        - has_color: bool
        - user_confirmed: bool (для STATE_4_OFFER → STATE_5)
        - has_delivery_data: bool
        - delivery_confirmed: bool
        - payment_proof_received: bool
    """
    selected_products = state.get("selected_products", []) or state.get("offered_products", [])
    has_products = len(selected_products) > 0
    
    # Извлекаем size/color из products
    has_size = False
    has_color = False
    if selected_products:
        first_product = selected_products[0]
        has_size = bool(first_product.get("size"))
        has_color = bool(first_product.get("color"))
    
    # Проверяем user_confirmed (для STATE_4_OFFER → STATE_5)
    current_state = state.get("current_state", "")
    user_confirmed = _detect_user_confirmation(
        current_state=current_state,
        intent=intent,
        user_message=user_message,
    )
    
    # Проверяем delivery data
    metadata = state.get("metadata", {}) or {}
    has_delivery_data = _has_delivery_data(metadata)
    delivery_confirmed = metadata.get("delivery_data_confirmed", False)
    payment_proof_received = metadata.get("payment_proof_received", False)
    
    return {
        "has_products": has_products,
        "has_size": has_size,
        "has_color": has_color,
        "user_confirmed": user_confirmed,
        "has_delivery_data": has_delivery_data,
        "delivery_confirmed": delivery_confirmed,
        "payment_proof_received": payment_proof_received,
    }


def _detect_user_confirmation(
    current_state: str,
    intent: str,
    user_message: str | None,
) -> bool:
    """
    Определить, подтвердил ли пользователь заказ (для STATE_4_OFFER → STATE_5).
    
    Проверяет:
    - intent == "PAYMENT_DELIVERY"
    - Keywords подтверждения в сообщении ("так", "беру", "да", "ок", etc.)
    
    КРИТИЧНО: Эта функция работает ТОЛЬКО для STATE_4_OFFER.
    Для других состояний всегда возвращает False.
    """
    from src.core.state_machine import State
    
    if current_state != State.STATE_4_OFFER.value:
        return False
    
    # Intent уже PAYMENT_DELIVERY
    if intent == "PAYMENT_DELIVERY":
        return True
    
    # Проверяем keywords подтверждения
    # КРИТИЧНО: Если найдено подтверждение - возвращаем True ВНЕ ЗАВИСИМОСТИ от других слов
    # Это гарантирует, что "Так" перебивает "Ціна?" при детекции подтверждения
    if user_message:
        import logging
        logger = logging.getLogger(__name__)
        
        from src.agents.langgraph.nodes.intent import INTENT_PATTERNS
        
        user_text_lower = user_message.lower()
        confirmation_keywords = INTENT_PATTERNS.get("CONFIRMATION", [])
        
        # Также проверяем специфичные keywords для offer
        offer_confirmation_keywords = [
            "беру",
            "оформлюємо",
            "оформляємо",
            "хочу замовити",
        ]
        
        # Проверяем product names (в OFFER state это тоже подтверждение)
        product_names = INTENT_PATTERNS.get("PRODUCT_NAMES", [])
        
        all_confirmation_keywords = confirmation_keywords + offer_confirmation_keywords + product_names
        
        # Проверяем наличие подтверждения
        found_keywords = [kw for kw in all_confirmation_keywords if kw in user_text_lower]
        if found_keywords:
            logger.info(
                "[FACTS] User confirmation detected in STATE_4_OFFER: keywords=%s (ignoring other intents like SIZE_HELP)",
                found_keywords[:3],  # Логируем первые 3 для краткости
            )
            return True
    
    return False


def _has_delivery_data(metadata: dict[str, Any]) -> bool:
    """Проверить, есть ли все необходимые данные для доставки."""
    has_name = bool(metadata.get("customer_name"))
    has_phone = bool(metadata.get("customer_phone"))
    has_city = bool(metadata.get("customer_city"))
    has_np = bool(metadata.get("customer_nova_poshta"))
    
    return has_name and has_phone and has_city and has_np

