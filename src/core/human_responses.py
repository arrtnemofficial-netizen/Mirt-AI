"""
Human-like Response Generator.
==============================
Makes AI responses indistinguishable from real human (Софія).

Key principles:
1. VARIABILITY - never same phrase twice
2. CASUAL SPEECH - like real Instagram DM
3. TYPOS occasionally - humans make mistakes
4. EMOJI usage like real person
5. Short messages - not walls of text
"""

from __future__ import annotations

import random
from typing import Literal


# =============================================================================
# RESPONSE VARIANTS (як пише справжня людина в Instagram)
# =============================================================================

TIMEOUT_RESPONSES = [
    "Чат підвис — повторіть повідомлення.",
    "Не підтягнуло останнє повідомлення. Напишіть ще раз.",
    "Зараз не бачу вашого повідомлення. Повторіть, будь ласка.",
    "Повідомлення не відобразилось. Надішліть ще раз.",
    "Є збій у чаті. Можете повторити?",
    "Загубилось повідомлення. Напишіть повторно.",
]

ERROR_RESPONSES = [
    "Зараз перевірю і напишу.",
    "Секунду, уточню деталі.",
    "Піймала збій. Зараз розберусь і відповім.",
    "Зараз гляну по системі й повернусь з відповіддю.",
    "Бачу, що не спрацювало. Зараз перевірю ще раз.",
]

PHOTO_ERROR_RESPONSES = [
    "Фото не відкрилось. Надішліть ще раз.",
    "Не бачу фото в чаті. Спробуйте повторно.",
    "Фото не підвантажилось. Надішліть ще раз.",
    "Зараз не відкривається фото. Можете надіслати повторно?",
    "Бачу повідомлення без фото. Надішліть його ще раз.",
]

PHOTO_ANALYSIS_ERROR_RESPONSES = [
    "На фото не видно деталей. Можете надіслати ближче/чіткіше?",
    "Фото темне — важко розгледіти. Надішліть інше, будь ласка.",
    "Потрібне фото крупним планом (спереду/бірка/деталь).",
    "Поки не можу точно визначити. Надішліть ще одне фото або короткий опис.",
]

PAYMENT_ERROR_RESPONSES = [
    "Зараз перевірю оформлення замовлення і напишу.",
    "Секунду, звірю дані по замовленню.",
    "Зараз уточню по оплаті/доставці й відповім.",
    "Схоже, з оформленням стався збій. Перевірю ще раз.",
]

ESCALATION_RESPONSES = [
    "Передам це колезі — він/вона підключиться до чату.",
    "Зараз підключу менеджера до розмови.",
    "Потрібно уточнити. Підключаю колегу.",
    "Зараз передам запит колезі, щоб швидше допомогли.",
]

NOT_FOUND_RESPONSES = [
    "Поки не знаходжу в каталозі. Уточніть, будь ласка, модель/колір.",
    "Не бачу такого в каталозі. Надішліть фото або короткий опис.",
    "Не знаходжу за запитом. Якщо є артикул/SKU — напишіть його.",
    "Не знаходжу зараз. Опишіть, будь ласка, іншими словами (колір, фасон, принт).",
]

# Typing indicators (shown before response)
TYPING_PHRASES = [
    "...",
    "пишу...",
    "думаю...",
    "шукаю...",
    "дивлюсь...",
]


# =============================================================================
# RESPONSE TYPE MAPPING
# =============================================================================

ResponseType = Literal[
    "timeout",
    "error",
    "photo_error",
    "photo_analysis_error",
    "payment_error",
    "escalation",
    "not_found",
]

_RESPONSE_MAP: dict[ResponseType, list[str]] = {
    "timeout": TIMEOUT_RESPONSES,
    "error": ERROR_RESPONSES,
    "photo_error": PHOTO_ERROR_RESPONSES,
    "photo_analysis_error": PHOTO_ANALYSIS_ERROR_RESPONSES,
    "payment_error": PAYMENT_ERROR_RESPONSES,
    "escalation": ESCALATION_RESPONSES,
    "not_found": NOT_FOUND_RESPONSES,
}


# =============================================================================
# PUBLIC API
# =============================================================================


def get_human_response(response_type: ResponseType) -> str:
    """
    Get a random human-like response for the given situation.

    Args:
        response_type: Type of response needed

    Returns:
        Random human-like message from the appropriate category
    """
    variants = _RESPONSE_MAP.get(response_type, ERROR_RESPONSES)
    return random.choice(variants)


def get_typing_indicator() -> str:
    """Get a random typing indicator."""
    return random.choice(TYPING_PHRASES)


def add_human_touch(text: str, typo_chance: float = 0.05) -> str:
    """
    Optionally add small human touches to text.

    Args:
        text: Original text
        typo_chance: Probability of adding a "typo" (0.0-1.0)

    Returns:
        Text with optional human touches
    """
    # Keep this subtle. By default, do nothing to avoid looking like imitation.
    if typo_chance <= 0:
        return text

    # Very rarely add a tiny punctuation variation.
    if random.random() < typo_chance and text and text[-1] == ".":
        return text[:-1]

    return text


# =============================================================================
# TYPING DELAY CONFIGURATION
# =============================================================================

# Delay range in seconds (simulates human typing speed)
TYPING_DELAY_MIN = 0.8  # Minimum delay
TYPING_DELAY_MAX = 2.5  # Maximum delay
TYPING_DELAY_PER_CHAR = 0.02  # Additional delay per character in response


def calculate_typing_delay(response_length: int) -> float:
    """
    Calculate realistic typing delay based on response length.

    Args:
        response_length: Number of characters in response

    Returns:
        Delay in seconds
    """
    base_delay = random.uniform(TYPING_DELAY_MIN, TYPING_DELAY_MAX)
    char_delay = min(response_length * TYPING_DELAY_PER_CHAR, 3.0)  # Cap at 3s
    return base_delay + char_delay
