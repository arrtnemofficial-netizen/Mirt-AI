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
    SUPABASE_UNAVAILABLE = "supabase_unavailable"
    MANYCHAT_UNAVAILABLE = "manychat_unavailable"
    VISION_FAILED = "vision_failed"
    CATALOG_EMPTY = "catalog_empty"
    PAYMENT_ERROR = "payment_error"
    CRM_UNAVAILABLE = "crm_unavailable"
    RATE_LIMITED = "rate_limited"
    UNKNOWN_ERROR = "unknown_error"


# =============================================================================
# FALLBACK MESSAGES (Ukrainian)
# =============================================================================

FALLBACK_MESSAGES: dict[FallbackType, dict[str, Any]] = {
    FallbackType.LLM_UNAVAILABLE: {
        "text": (
            "Вибачте, у мене зараз технічні труднощі 🔧\n"
            "Спробуйте написати ще раз через хвилинку, або напишіть напряму менеджеру."
        ),
        "quick_replies": ["Спробувати ще раз", "Написати менеджеру"],
        "should_escalate": False,
        "retry_after_seconds": 60,
    },
    FallbackType.LLM_TIMEOUT: {
        "text": ("Ой, щось довго думаю... 🤔\nДавайте спробуємо ще раз? Повторіть ваше питання."),
        "quick_replies": ["Повторити"],
        "should_escalate": False,
        "retry_after_seconds": 30,
    },
    FallbackType.SUPABASE_UNAVAILABLE: {
        "text": (
            "Вибачте, не можу зараз зберегти дані.\n"
            "Ваше повідомлення я отримав, продовжуйте спілкування!"
        ),
        "quick_replies": [],
        "should_escalate": False,
        "retry_after_seconds": 120,
    },
    FallbackType.MANYCHAT_UNAVAILABLE: {
        "text": None,  # Silent - user won't see this
        "quick_replies": [],
        "should_escalate": True,
        "retry_after_seconds": 60,
    },
    FallbackType.VISION_FAILED: {
        "text": (
            "Не вдалося розпізнати фото 📷\n"
            "Спробуйте надіслати ще раз або опишіть що ви шукаєте словами."
        ),
        "quick_replies": ["Описати словами", "Надіслати інше фото"],
        "should_escalate": False,
        "retry_after_seconds": 0,
    },
    FallbackType.CATALOG_EMPTY: {
        "text": (
            "Не знайшла такого товару в каталозі 🔍\n"
            "Можливо ви шукаєте щось інше? Опишіть детальніше."
        ),
        "quick_replies": ["Показати каталог", "Допомога"],
        "should_escalate": False,
        "retry_after_seconds": 0,
    },
    FallbackType.PAYMENT_ERROR: {
        "text": (
            "Виникла помилка з оформленням замовлення.\n"
            "Не хвилюйтесь, менеджер зв'яжеться з вами найближчим часом!"
        ),
        "quick_replies": ["Зателефонувати"],
        "should_escalate": True,
        "retry_after_seconds": 0,
    },
    FallbackType.CRM_UNAVAILABLE: {
        "text": ("Замовлення прийнято! ✅\nМенеджер зв'яжеться з вами для підтвердження."),
        "quick_replies": [],
        "should_escalate": True,  # Notify manager
        "retry_after_seconds": 300,
    },
    FallbackType.RATE_LIMITED: {
        "text": ("Занадто багато повідомлень 😅\nЗачекайте трохи і спробуйте знову."),
        "quick_replies": [],
        "should_escalate": False,
        "retry_after_seconds": 30,
    },
    FallbackType.UNKNOWN_ERROR: {
        "text": (
            "Щось пішло не так 😔\nСпробуйте ще раз або напишіть /restart щоб почати спочатку."
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
    elif "supabase" in error_str or "postgres" in error_str:
        fallback_type = FallbackType.SUPABASE_UNAVAILABLE
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
