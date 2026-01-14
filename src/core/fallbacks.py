"""
Fallbacks - graceful degradation responses.
============================================
Fallback відповіді коли зовнішні сервіси недоступні.

Принципи:
1. ЗАВЖДИ відповідай користувачу (ніколи не мовчи)
2. Чесно повідом про проблему
3. Запропонуй альтернативу
4. Збережи context для retry

Використання:
    from src.core.fallbacks import get_fallback_response, FallbackType

    response = get_fallback_response(FallbackType.LLM_UNAVAILABLE)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any


logger = logging.getLogger(__name__)


class FallbackType(Enum):
    """Типи fallback сценаріїв."""

    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_TIMEOUT = "llm_timeout"
    DATABASE_UNAVAILABLE = "database_unavailable"
    MANYCHAT_UNAVAILABLE = "manychat_unavailable"
    VISION_FAILED = "vision_failed"
    CATALOG_EMPTY = "catalog_empty"
    PAYMENT_ERROR = "payment_error"
    CRM_UNAVAILABLE = "crm_unavailable"
    RATE_LIMITED = "rate_limited"
    UNKNOWN_ERROR = "unknown_error"


# =============================================================================
# UI MESSAGES (SSOT for User-Facing Strings)
# =============================================================================

def get_thank_you_message() -> str:
    """Standard Thank You message."""
    return "Дякуємо за замовлення ⭐️\nГарного вам вечора та мирного неба 🕊️"


def get_subscribe_message() -> str:
    """Standard Subscribe request (Security focus)."""
    return (
        "Зараз великі магазини, такі як наш, конкуренти часто намагаються зламувати. "
        "Щоб ви нас не втратили, підпишіться, будь ласка, також на нашу другу офіційну сторінку. @mirt_original"
    )


def get_vision_failed_message() -> str:
    """Friendly vision failure message."""
    return "Ой, я трохи розгубилась і не можу точно зрозуміти, яка це модель на фото 🙈 Покажу менеджеру, він гляне і відпише вам!"


def get_payment_fallback_text() -> str:
    """Fallback when Payment LLM fails."""
    return "Щоб я могла все оформити, напишіть, будь ласка: ПІБ, телефон та куди відправляти (місто/відділення) ✍️"



# =============================================================================
# FALLBACK MESSAGES (Ukrainian)
# =============================================================================

FALLBACK_MESSAGES: dict[FallbackType, dict[str, Any]] = {
    FallbackType.LLM_UNAVAILABLE: {
        "text": (
            "Зараз перевіряю інформацію, зачекайте хвилинку, будь ласка... 👩‍💻\n"
            "Якщо довго не відповідаю - можете написати моєму колезі."
        ),
        "quick_replies": ["Написати менеджеру"],
        "should_escalate": False,
        "retry_after_seconds": 60,
    },
    FallbackType.LLM_TIMEOUT: {
        "text": ("Заточнюю на складі... Ще секундочку ⏳"),
        "quick_replies": [],
        "should_escalate": False,
        "retry_after_seconds": 30,
    },
    FallbackType.DATABASE_UNAVAILABLE: {
        "text": (
            "Зараз поганий зв'язок, не можу записати дані.\n"
            "Надішліть, будь ласка, ще раз через хвилину."
        ),
        "quick_replies": [],
        "should_escalate": False,
        "retry_after_seconds": 120,
    },
    FallbackType.MANYCHAT_UNAVAILABLE: {
        "text": None,  # Silent
        "quick_replies": [],
        "should_escalate": True,
        "retry_after_seconds": 60,
    },
    FallbackType.VISION_FAILED: {
        "text": (
            "Погано видно деталі на фото.\n"
            "Можете зробити інше фото або просто напишіть, що ви шукаєте?"
        ),
        "quick_replies": ["Описати словами", "Надіслати інше фото"],
        "should_escalate": False,
        "retry_after_seconds": 0,
    },
    FallbackType.CATALOG_EMPTY: {
        "text": (
            "На жаль, саме такої моделі зараз немає в наявності.\n"
            "Давайте підберу вам щось схоже? Що для вас важливо?"
        ),
        "quick_replies": ["Показати каталог", "Допомога"],
        "should_escalate": False,
        "retry_after_seconds": 0,
    },
    FallbackType.PAYMENT_ERROR: {
        "text": (
            "Щось система не пропускає замовлення.\n"
            "Я зараз передам інформацію старшому менеджеру, він перевірить вручну."
        ),
        "quick_replies": ["Зателефонувати"],
        "should_escalate": True,
        "retry_after_seconds": 0,
    },
    FallbackType.CRM_UNAVAILABLE: {
        "text": ("Замовлення зафіксувала! ✅\nЗараз передам на склад для підтвердження."),
        "quick_replies": [],
        "should_escalate": True,
        "retry_after_seconds": 300,
    },
    FallbackType.RATE_LIMITED: {
        "text": ("Ви дуже швидко пишете, я не встигаю відповідати) Давайте по черзі."),
        "quick_replies": [],
        "should_escalate": False,
        "retry_after_seconds": 30,
    },
    FallbackType.UNKNOWN_ERROR: {
        "text": (
            "Вибачте, не зрозуміла останнє повідомлення.\nМожете повторити?"
        ),
        "quick_replies": ["Спробувати ще раз", "/restart"],
        "should_escalate": False,
        "retry_after_seconds": 10,
    },
}


# =============================================================================
# FALLBACK FUNCTIONS
# =============================================================================


def get_fallback_response(
    fallback_type: FallbackType,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Отримати fallback відповідь для типу помилки.

    Args:
        fallback_type: Тип fallback сценарію
        context: Додатковий контекст (user_id, session_id тощо)

    Returns:
        Dict з text, quick_replies, should_escalate, retry_after_seconds
    """
    fallback = FALLBACK_MESSAGES.get(fallback_type, FALLBACK_MESSAGES[FallbackType.UNKNOWN_ERROR])

    logger.warning(
        "Fallback triggered: type=%s, escalate=%s, context=%s",
        fallback_type.value,
        fallback.get("should_escalate"),
        context,
    )

    return {
        "text": fallback["text"],
        "quick_replies": fallback.get("quick_replies", []),
        "should_escalate": fallback.get("should_escalate", False),
        "retry_after_seconds": fallback.get("retry_after_seconds", 0),
        "fallback_type": fallback_type.value,
    }


def get_fallback_text(fallback_type: FallbackType) -> str | None:
    """Отримати тільки текст fallback (для простих випадків)."""
    fallback = FALLBACK_MESSAGES.get(fallback_type, FALLBACK_MESSAGES[FallbackType.UNKNOWN_ERROR])
    return fallback.get("text")


def should_escalate(fallback_type: FallbackType) -> bool:
    """Перевірити чи потрібна ескалація до менеджера."""
    fallback = FALLBACK_MESSAGES.get(fallback_type, {})
    return fallback.get("should_escalate", False)


# =============================================================================
# CONTEXTUAL FALLBACKS
# =============================================================================


def get_contextual_fallback(
    error: Exception,
    current_state: str | None = None,
    intent: str | None = None,
) -> dict[str, Any]:
    """
    Визначити тип fallback на основі помилки та контексту.

    Args:
        error: Виняток що стався
        current_state: Поточний стан діалогу
        intent: Intent користувача

    Returns:
        Fallback response dict
    """
    error_str = str(error).lower()
    error_type = type(error).__name__

    # Determine fallback type based on error
    if "timeout" in error_str or "timed out" in error_str:
        fallback_type = FallbackType.LLM_TIMEOUT
    elif "rate limit" in error_str or "429" in error_str:
        fallback_type = FallbackType.RATE_LIMITED
    elif "postgres" in error_str or "database" in error_str or "psycopg" in error_str:
        fallback_type = FallbackType.DATABASE_UNAVAILABLE
    elif "manychat" in error_str:
        fallback_type = FallbackType.MANYCHAT_UNAVAILABLE
    elif "vision" in error_str or "image" in error_str:
        fallback_type = FallbackType.VISION_FAILED
    elif "crm" in error_str or "snitkix" in error_str:
        fallback_type = FallbackType.CRM_UNAVAILABLE
    elif "payment" in current_state.lower() if current_state else False:
        fallback_type = FallbackType.PAYMENT_ERROR
    else:
        fallback_type = FallbackType.UNKNOWN_ERROR

    return get_fallback_response(
        fallback_type,
        context={
            "error_type": error_type,
            "current_state": current_state,
            "intent": intent,
        },
    )


# =============================================================================
# CACHED RESPONSES (for when LLM is down)
# =============================================================================

CACHED_RESPONSES: dict[str, str] = {
    "greeting": "Привіт! Я Mirt - ваш помічник з вибору дитячого одягу 👋",
    "catalog": "Ми пропонуємо костюми для хлопчиків і дівчаток від 122 до 164 розміру. Надішліть фото або опишіть що шукаєте!",
    "payment": "Для оформлення замовлення потрібно: ім'я, телефон, місто та відділення Нової Пошти.",
    "help": "Я можу допомогти підібрати костюм по фото або опису. Напишіть розмір дитини (зріст) і що шукаєте!",
}


def get_cached_response(intent: str) -> str | None:
    """Отримати cached відповідь для basic intents (коли LLM недоступний)."""
    intent_lower = intent.lower() if intent else ""

    if "greet" in intent_lower or "hello" in intent_lower:
        return CACHED_RESPONSES["greeting"]
    if "catalog" in intent_lower or "product" in intent_lower:
        return CACHED_RESPONSES["catalog"]
    if "payment" in intent_lower or "order" in intent_lower:
        return CACHED_RESPONSES["payment"]
    if "help" in intent_lower:
        return CACHED_RESPONSES["help"]

    return None
