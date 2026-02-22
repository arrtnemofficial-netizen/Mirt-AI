"""
Intent Detection Node - Smart routing.
======================================
Quick classification for conditional edge routing.
Full intent analysis happens in LLM, but this enables fast routing.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.langgraph.intent.policy import select_intents
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
        "чек",
        "квитанці",
    ],
    # Confirmation words that mean "yes" in OFFER state
    "CONFIRMATION": [
        "так",
        "да",
        "yes",
        "ок",
        "ok",
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
    # Product category browsing - general type requests
    "PRODUCT_CATEGORY": [
        # Костюми
        "костюм",
        "костюмчик",
        "комплект",
        # Сукні
        "сукн",  # сукня, сукню, сукні
        "плаття",
        "платтячко",
        # Верхній одяг
        "тренч",
        "куртка",
        "курточка",
        "плащ",
        # Штани
        "штани",
        "штанці",
        "брюки",
        "джогери",
        # Верх
        "блуз",  # блуза, блузка, блузу
        "кофт",  # кофта, кофту
        "світшот",
        "худі",
        # General
        "одяг",
        "річ",
        "щось на",  # "щось на свято"
    ],
    "SIZE_HELP": [
        "зріст",
        "розмір",
        "вік",
        "см",
        "років",
        "рік",
        "міс",
        "скільки років",
        "скільки см",
        "який розмір",
        "підбери",
        "підійде",
    ],
    "COLOR_HELP": [
        # Generic color questions (specific patterns to avoid false positives)
        "який колір",
        "які кольори",
        "інший колір",  # More specific than just "інший"
        "є в кольорі",  # More specific than "є в "
        "колір є",
        # Specific colors (longer stems to avoid false positives)
        "чорний",
        "чорного",
        "чорному",
        "чорним",
        "білий",
        "білого",
        "білому",
        "білим",
        "рожев",  # рожевий, рожевого - safe, no FP
        "синій",
        "синього",
        "синьому",  # NOT "син" - FP with "син" (son)!
        "червон",  # червоний - safe
        "зелен",  # зелений - safe
        "жовт",  # жовтий - safe
        "помаранч",  # помаранчевий - safe
        "сірий",
        "сірого",
        "сірому",  # NOT "сір" - FP with "сір" (cheese)!
        "молоч",  # молочний - safe
        "бордо",  # бордо - safe
        "шоколад",  # шоколадний - safe
        "бежев",  # бежевий - safe
        "малинов",  # малиновий - safe
    ],
    "COMPLAINT": [
        "скарга",
        "проблем",
        "повернен",
        "поверн",
        "брак",
        "жалоба",
        "обман",
        "не працює",
        "зламан",
        "погано",
        "відмов",
    ],
    # PHOTO_IDENT - used when has_image=True (user sent photo)
    # Note: This is not matched via keywords, only via has_image flag
    "PHOTO_IDENT": [
        # These are kept for reference but detection is via has_image flag
    ],
    # REQUEST_PHOTO - user asks to see a product photo (no image attached)
    "REQUEST_PHOTO": [
        "покажи фото",
        "можна фото",
        "є фото",
        "скинь фото",
        "фотку",
        "як виглядає",
        "покажіть",
        "хочу побачити",
        "можна подивитись",
        "реальне фото",
        "живе фото",
        "фото вживу",
    ],
    "DISCOVERY_OR_QUESTION": [
        # NOTE: Clothing types (костюм, сукня, тренч) are now in PRODUCT_CATEGORY
        # which has higher priority. Keep only general discovery keywords here.
        "покаж",
        "є",  # "чи є?"
        "хочу",  # "хочу щось"
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
    # Thank you / small talk - end of conversation
    "THANKYOU_SMALLTALK": [
        "дякую",
        "дякуємо",
        "спасибі",
        "дуже вдячна",
        "вдячна",
        "ок",
        "окей",
        "добре",
        "зрозуміло",
        "гарного дня",
        "до побачення",
        "бувайте",
        # Refusals (acts as closure)
        "ні",
        "не",
        "не хочу",
        "не треба",
        "відміна",
        "відмова",
        "скасувати",
        "no",
        "cancel",
    ],
}

# In STATE_5, these phrases are treated as explicit refusal/cancel and can exit payment flow.
STATE5_EXPLICIT_CANCEL_PATTERNS = [
    "відміна",
    "відмов",
    "скасувати",
    "не хочу",
    "не треба",
    "передум",
    "cancel",
]


def detect_intent_from_text(
    text: str,
    has_image: bool,
    current_state: str,
) -> str:
    """Backward-compatible wrapper: returns only primary intent."""
    selection = detect_intent_candidates_from_text(
        text=text,
        has_image=has_image,
        current_state=current_state,
    )
    return selection["primary_intent"]


def detect_intent_candidates_from_text(
    text: str,
    has_image: bool,
    current_state: str,
    top_k: int = 3,
) -> dict[str, Any]:
    """Detect intent candidates and resolve primary/deferred intents by policy."""
    text_lower = text.lower().strip()
    min_top_k = max(top_k, 3)

    # Special cases first
    special = _check_special_cases(text_lower, has_image, current_state)
    if special:
        candidates = [special, "DISCOVERY_OR_QUESTION", "THANKYOU_SMALLTALK"]
        selection = select_intents(candidates)
        return {
            "primary_intent": selection.primary_intent,
            "deferred_intents": selection.deferred_intents,
            "intent_candidates": candidates[:min_top_k],
        }

    candidates = _collect_keyword_candidates(text_lower, len(text), min_top_k)
    selection = select_intents(candidates)

    return {
        "primary_intent": selection.primary_intent,
        "deferred_intents": selection.deferred_intents,
        "intent_candidates": candidates,
    }


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

    # Payment context takes priority in payment state - BUT allow off-topic intents
    if current_state == "STATE_5_PAYMENT_DELIVERY":
        # In payment state, most inputs are payment-related (size, address, phone, etc.)
        # BUT: Allow off-topic intents (PRODUCT_CATEGORY, REQUEST_PHOTO) to be handled
        # by agent node with snippets-first policy, then return to payment

        # Explicit complaints: let keyword matching handle
        for keyword in INTENT_PATTERNS["COMPLAINT"]:
            if keyword in text_lower:
                return None  # Let keyword matching handle complaints

        # Explicit refusal/cancel should preserve legacy exit behavior.
        for keyword in STATE5_EXPLICIT_CANCEL_PATTERNS:
            if keyword in text_lower:
                logger.info("Intent: THANKYOU_SMALLTALK (explicit cancel in payment state)")
                return "THANKYOU_SMALLTALK"

        # Off-topic intents: allow them (will be handled by agent with snippets-first)
        for keyword in INTENT_PATTERNS["PRODUCT_CATEGORY"]:
            if keyword in text_lower:
                logger.info("Intent: PRODUCT_CATEGORY (in payment state, allowing off-topic)")
                return "PRODUCT_CATEGORY"

        for keyword in INTENT_PATTERNS["REQUEST_PHOTO"]:
            if keyword in text_lower:
                logger.info("Intent: REQUEST_PHOTO (in payment state, allowing off-topic)")
                return "REQUEST_PHOTO"

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


def _collect_keyword_candidates(text_lower: str, text_len: int, top_k: int) -> list[str]:
    """Collect top-k intent candidates using keyword hit counts."""
    scored: list[tuple[str, int]] = []

    candidate_intents = [
        "PAYMENT_DELIVERY",
        "COMPLAINT",
        "SIZE_HELP",
        "COLOR_HELP",
        "REQUEST_PHOTO",
        "PRODUCT_CATEGORY",
        "DISCOVERY_OR_QUESTION",
    ]

    if text_len < 50:
        candidate_intents.extend(["GREETING_ONLY", "THANKYOU_SMALLTALK"])

    for intent in candidate_intents:
        keywords = INTENT_PATTERNS.get(intent, [])
        score = sum(1 for keyword in keywords if keyword in text_lower)
        if score > 0:
            scored.append((intent, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    candidates = [intent for intent, _score in scored]

    if "DISCOVERY_OR_QUESTION" not in candidates:
        candidates.append("DISCOVERY_OR_QUESTION")
    if "THANKYOU_SMALLTALK" not in candidates:
        candidates.append("THANKYOU_SMALLTALK")
    if "GREETING_ONLY" not in candidates:
        candidates.append("GREETING_ONLY")

    return candidates[:top_k]


async def intent_detection_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Detect intent from user input for smart routing.

    This runs BEFORE LLM to enable conditional edges.
    Fast and lightweight - no API calls.
    """
    # Check for image FIRST - but respect dialog_phase for phase-aware routing
    metadata = state.get("metadata", {})
    has_image_early = state.get("has_image", False) or metadata.get("has_image", False)
    dialog_phase = state.get("dialog_phase", "INIT")

    # Get user message for explicit "new product" detection
    from .utils import extract_user_message
    user_content_early = extract_user_message(state.get("messages", []))

    if has_image_early:
        # CRITICAL: Use unified photo purpose detection (SSOT)
        from src.agents.langgraph.rules.photo_purpose import determine_photo_purpose

        photo_purpose, reason = determine_photo_purpose(state, user_content_early)

        # Map photo purpose to intent
        if photo_purpose == "product_ident":
            intent = "PHOTO_IDENT"
            image_context = "product_identification"
            if reason == "explicit_new_product_trigger":
                image_context = "explicit_new_product"
                metadata["explicit_new_product_trigger"] = True
            elif reason == "product_addition_intent_in_payment_phase":
                image_context = "product_addition"
                metadata["product_addition_context"] = True
            elif reason == "smart_rerun_no_products_or_asks_identification":
                image_context = "smart_rerun"

            logger.info(
                "Intent: PHOTO_IDENT (photo_purpose=%s, reason=%s)",
                photo_purpose,
                reason,
            )
            return {
                "detected_intent": intent,
                "has_image": True,
                "image_url": metadata.get("image_url"),
                "metadata": {
                    **metadata,
                    "has_image": True,
                    "image_context": image_context,
                    "primary_intent": intent,
                    "deferred_intents": ["DISCOVERY_OR_QUESTION", "THANKYOU_SMALLTALK"],
                    "has_deferred_intents": True,
                    "intent_candidates": [intent, "DISCOVERY_OR_QUESTION", "THANKYOU_SMALLTALK"],
                },
                "step_number": state.get("step_number", 0) + 1,
            }
        elif photo_purpose == "transactional":
            logger.info(
                "Intent: PAYMENT_DELIVERY (photo_purpose=%s, reason=%s)",
                photo_purpose,
                reason,
            )
            return {
                "detected_intent": "PAYMENT_DELIVERY",
                "has_image": True,
                "image_url": metadata.get("image_url"),
                "metadata": {
                    **metadata,
                    "has_image": True,
                    "image_context": "payment",
                    "primary_intent": "PAYMENT_DELIVERY",
                    "deferred_intents": ["DISCOVERY_OR_QUESTION", "THANKYOU_SMALLTALK"],
                    "has_deferred_intents": True,
                    "intent_candidates": ["PAYMENT_DELIVERY", "DISCOVERY_OR_QUESTION", "THANKYOU_SMALLTALK"],
                },
                "step_number": state.get("step_number", 0) + 1,
            }
        else:  # context
            logger.info(
                "Intent: DISCOVERY_OR_QUESTION (photo_purpose=%s, reason=%s, handle in context)",
                photo_purpose,
                reason,
            )
            return {
                "detected_intent": "DISCOVERY_OR_QUESTION",  # Let agent decide based on context
                "has_image": True,
                "image_url": metadata.get("image_url"),
                "metadata": {
                    **metadata,
                    "has_image": True,
                    "image_context": "ongoing_conversation",
                    "primary_intent": "DISCOVERY_OR_QUESTION",
                    "deferred_intents": ["THANKYOU_SMALLTALK", "GREETING_ONLY"],
                    "has_deferred_intents": True,
                    "intent_candidates": ["DISCOVERY_OR_QUESTION", "THANKYOU_SMALLTALK", "GREETING_ONLY"],
                },
                "step_number": state.get("step_number", 0) + 1,
            }

    # Skip if already escalating (only for non-photo messages)
    if state.get("should_escalate"):
        return {
            "detected_intent": "ESCALATION",
            "metadata": {
                **state.get("metadata", {}),
                "primary_intent": "ESCALATION",
                "deferred_intents": [],
                "has_deferred_intents": False,
                "intent_candidates": ["ESCALATION", "COMPLAINT", "PAYMENT_DELIVERY"],
            },
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

    # Detect intent candidates + policy-selected primary/deferred intents
    selection = detect_intent_candidates_from_text(
        text=user_content,
        has_image=has_image,
        current_state=metadata.current_state.value,
    )
    detected_intent = selection["primary_intent"]
    deferred_intents = selection["deferred_intents"]
    intent_candidates = selection["intent_candidates"]

    logger.debug(
        "Intent detected: %s, deferred=%s, candidates=%s (text=%s, has_image=%s, state=%s)",
        detected_intent,
        deferred_intents,
        intent_candidates,
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
            "primary_intent": detected_intent,
            "deferred_intents": deferred_intents,
            "has_deferred_intents": bool(deferred_intents),
            "intent_candidates": intent_candidates,
        },
        "step_number": state.get("step_number", 0) + 1,
    }
