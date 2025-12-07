"""
Intent Detection Node - Smart routing.
======================================
Quick classification for conditional edge routing.
Full intent analysis happens in LLM, but this enables fast routing.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.input_validator import validate_input_metadata


logger = logging.getLogger(__name__)


# Intent keywords for quick detection
INTENT_PATTERNS = {
    "PAYMENT_DELIVERY": [
        "купую",
        "беру",
        "оплата",
        "реквізит",
        "замовл",
        "оформ",
        "карта",
        "переказ",
        "оплачу",
        "доставк",
        "нова пошта",
        "хочу куп",  # explicit purchase intent
    ],
    # Confirmation words that mean "yes" in OFFER state
    "CONFIRMATION": [
        "так",
        "да",
        "yes",
        "ок",
        "добре",
        "згодна",
        "згоден",
        "підходить",
        "давай",
        "давайте",
        "можна",
        "хочу",
        "буду",
        "годі",
        "файно",
        "супер",
    ],
    # Product names for selection in OFFER state
    "PRODUCT_NAMES": [
        "лагуна",
        "мрія",
        "ритм",
        "каприз",
        "валері",
        "мерея",
        "анна",
        "тренч",
        "еліт",
        "зірка",
        "софія",
        "вікторія",
        "мілана",
        "діана",
        "перший",
        "другий",
        "третій",
        "1",
        "2",
        "3",  # selection by number
    ],
    "SIZE_HELP": [
        "зріст",
        "розмір",
        "вік",
        "см",
        "років",
        "рік",
        "міс",
        "скільки",
        "який розмір",
        "підбери",
        "підійде",
    ],
    "COLOR_HELP": [
        "колір",
        "кольор",
        "інший",
        "чорн",
        "біл",
        "рожев",
        "синій",
        "червон",
        "зелен",
    ],
    "COMPLAINT": [
        "скарга",
        "проблем",
        "повернен",
        "брак",
        "жалоба",
        "обман",
        "не працює",
        "зламан",
        "погано",
        "відмов",
    ],
    "PHOTO_IDENT": [
        "фото",
        "фотографія",
        "зображення",
        "покажи фото",
        "можна фото",
        "дивись фото",
        "картинка",
        "знімок",
        "фотк",
    ],
    "DISCOVERY_OR_QUESTION": [
        "сукн",
        "костюм",
        "тренч",
        "плаття",
        "покаж",
        "є",
        "хочу",
        "підбери",
        "порадь",
        "шукаю",
        "ціна",
        "скільки кошт",
    ],
    "GREETING_ONLY": [
        "привіт",
        "вітаю",
        "добр",
        "hello",
        "hi",
        "хай",
    ],
}


def detect_intent_from_text(
    text: str,
    has_image: bool,
    current_state: str,
) -> str:
    """
    Quick intent detection based on keywords and context.

    Priority:
    1. Payment context in payment state (no matter what)
    2. Photo present -> PHOTO_IDENT
    3. Keyword matching
    4. Default to DISCOVERY_OR_QUESTION
    """
    text_lower = text.lower().strip()

    # Special cases first
    special = _check_special_cases(text_lower, has_image, current_state)
    if special:
        return special

    # Keyword matching in priority order
    return _match_keywords(text_lower, len(text))


def _check_special_cases(text_lower: str, has_image: bool, current_state: str) -> str | None:
    """Check special cases before keyword matching."""
    # Empty text with image = definitely photo identification
    if not text_lower and has_image:
        return "PHOTO_IDENT"

    # In OFFER state: payment keywords, confirmations, or product names = PAYMENT
    if current_state == "STATE_4_OFFER":
        # Payment keywords
        for keyword in INTENT_PATTERNS["PAYMENT_DELIVERY"]:
            if keyword in text_lower:
                logger.info(
                    "Intent override: PAYMENT_DELIVERY in OFFER state (payment keyword: %s)",
                    keyword,
                )
                return "PAYMENT_DELIVERY"
        # Confirmation words (так, да, ок, etc.)
        for keyword in INTENT_PATTERNS["CONFIRMATION"]:
            if keyword in text_lower:
                logger.info(
                    "Intent override: PAYMENT_DELIVERY in OFFER state (confirmation: %s)", keyword
                )
                return "PAYMENT_DELIVERY"
        # Product name selection (лагуна, мрія, etc.)
        for keyword in INTENT_PATTERNS["PRODUCT_NAMES"]:
            if keyword in text_lower:
                logger.info(
                    "Intent override: PAYMENT_DELIVERY in OFFER state (product selection: %s)",
                    keyword,
                )
                return "PAYMENT_DELIVERY"

    # Payment context takes priority in payment state - ANY input continues payment flow
    if current_state == "STATE_5_PAYMENT_DELIVERY":
        # In payment state, most inputs are payment-related (size, address, phone, etc.)
        # Only explicit questions or complaints should break out
        for keyword in INTENT_PATTERNS["COMPLAINT"]:
            if keyword in text_lower:
                return None  # Let keyword matching handle complaints
        # Everything else in payment state stays in payment
        logger.info("Intent: PAYMENT_DELIVERY (in payment state, continuing flow)")
        return "PAYMENT_DELIVERY"

    # Photo identification ONLY if user sent text that looks like photo query
    # OR if there's no meaningful text (just "ціна" etc with image)
    if has_image:
        # Check if text is a payment/action keyword - don't override to PHOTO_IDENT
        for keyword in INTENT_PATTERNS["PAYMENT_DELIVERY"]:
            if keyword in text_lower:
                return None  # Let keyword matching handle it
        return "PHOTO_IDENT"

    return None


def _match_keywords(text_lower: str, text_len: int) -> str:
    """Match keywords in priority order."""
    # Priority order for keyword matching
    priority_intents = [
        "PAYMENT_DELIVERY",
        "COMPLAINT",
        "SIZE_HELP",
        "COLOR_HELP",
    ]

    for intent in priority_intents:
        for keyword in INTENT_PATTERNS[intent]:
            if keyword in text_lower:
                return intent

    # Greeting (only if short message)
    if text_len < 30:
        for keyword in INTENT_PATTERNS["GREETING_ONLY"]:
            if keyword in text_lower:
                return "GREETING_ONLY"

    # Discovery/questions
    for keyword in INTENT_PATTERNS["DISCOVERY_OR_QUESTION"]:
        if keyword in text_lower:
            return "DISCOVERY_OR_QUESTION"

    return "DISCOVERY_OR_QUESTION"


async def intent_detection_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Detect intent from user input for smart routing.

    This runs BEFORE LLM to enable conditional edges.
    Fast and lightweight - no API calls.
    """
    # Skip if already escalating
    if state.get("should_escalate"):
        return {
            "detected_intent": "ESCALATION",
            "step_number": state.get("step_number", 0) + 1,
        }

    # Validate metadata
    metadata = validate_input_metadata(state.get("metadata", {}))

    # Get latest user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message

    user_content = extract_user_message(state.get("messages", []))

    # Check for image
    has_image = metadata.has_image or bool(metadata.image_url)
    image_url = metadata.image_url

    # Detect intent
    detected_intent = detect_intent_from_text(
        text=user_content,
        has_image=has_image,
        current_state=metadata.current_state.value,
    )

    logger.debug(
        "Intent detected: %s (text=%s, has_image=%s, state=%s)",
        detected_intent,
        user_content[:50] if user_content else "",
        has_image,
        metadata.current_state.value,
    )

    return {
        "detected_intent": detected_intent,
        "has_image": has_image,
        "image_url": image_url,
        "metadata": {
            **state.get("metadata", {}),
            "has_image": has_image,
            "image_url": image_url,
        },
        "step_number": state.get("step_number", 0) + 1,
    }
