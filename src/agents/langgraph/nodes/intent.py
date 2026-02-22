"""
Intent Detection Node - Smart routing.
======================================
Quick classification for conditional edge routing.
Full intent analysis happens in LLM, but this enables fast routing.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.langgraph.intent.models import IntentDecision
from src.agents.langgraph.intent.policy import select_intents
from src.agents.langgraph.memory_gateway import MemoryGateway, upsert_facts_from_text
from src.conf.config import settings
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

def detect_intent_from_text(
    text: str,
    has_image: bool,
    current_state: str,
) -> IntentDecision:
    """Detect intent and return structured decision for safe routing."""
    selection = detect_intent_candidates_from_text(
        text=text,
        has_image=has_image,
        current_state=current_state,
    )
    return selection["decision"]


def detect_intent_candidates_from_text(
    text: str,
    has_image: bool,
    current_state: str,
    top_k: int = 3,
) -> dict[str, Any]:
    """Detect top intent candidates and resolve ambiguity/confidence gates."""
    text_lower = (text or "").lower().strip()
    min_top_k = max(top_k, 3)

    special = _check_special_cases(text_lower, has_image, current_state)
    if special:
        candidates = [special, "DISCOVERY_OR_QUESTION", "THANKYOU_SMALLTALK"]
        selection = select_intents(candidates)
        decision = IntentDecision(
            primary_intent=selection.primary_intent,
            confidence=0.95,
            secondary_intents=selection.deferred_intents,
            ambiguous_flag=False,
            reason="special_case",
        )
        return {
            "decision": decision,
            "primary_intent": decision.primary_intent,
            "deferred_intents": decision.secondary_intents,
            "intent_candidates": candidates[:min_top_k],
            "confidence": decision.confidence,
            "ambiguous_flag": decision.ambiguous_flag,
            "reason": decision.reason,
        }

    scored_candidates = _score_keyword_candidates(text_lower=text_lower, text_len=len(text or ""), top_k=min_top_k)
    candidates = [intent for intent, _ in scored_candidates]
    selection = select_intents(candidates)
    top_score = scored_candidates[0][1] if scored_candidates else 0
    second_score = scored_candidates[1][1] if len(scored_candidates) > 1 else 0

    base_confidence = min(0.95, 0.45 + (top_score * 0.18))
    mixed_margin = top_score - second_score
    is_mixed = second_score > 0 and mixed_margin <= settings.INTENT_AMBIGUOUS_MARGIN
    low_confidence = base_confidence < settings.INTENT_LOW_CONFIDENCE_THRESHOLD
    ambiguous_flag = bool(is_mixed or low_confidence)

    if ambiguous_flag:
        primary_intent = "AMBIGUOUS"
        reason = "mixed_intent" if is_mixed else "low_confidence"
        secondary_intents = [selection.primary_intent, *selection.deferred_intents]
    else:
        primary_intent = selection.primary_intent
        reason = "clear_match"
        secondary_intents = selection.deferred_intents

    decision = IntentDecision(
        primary_intent=primary_intent,
        confidence=round(base_confidence, 2),
        secondary_intents=list(dict.fromkeys(secondary_intents)),
        ambiguous_flag=ambiguous_flag,
        reason=reason,
    )

    if settings.INTENT_SHADOW_LOGGING:
        logger.info(
            "intent.shadow decision=%s confidence=%.2f ambiguous=%s reason=%s top=%s second=%s text=%s",
            decision.primary_intent,
            decision.confidence,
            decision.ambiguous_flag,
            decision.reason,
            top_score,
            second_score,
            (text or "")[:120],
        )

    return {
        "decision": decision,
        "primary_intent": decision.primary_intent,
        "deferred_intents": decision.secondary_intents,
        "intent_candidates": candidates,
        "confidence": decision.confidence,
        "ambiguous_flag": decision.ambiguous_flag,
        "reason": decision.reason,
    }


def _check_special_cases(text_lower: str, has_image: bool, _current_state: str) -> str | None:
    """Check intent-only special cases before keyword matching."""
    # Empty text with image = definitely photo identification
    if not text_lower and has_image:
        return "PHOTO_IDENT"

    # Photo identification only when image is attached and text is not clearly payment-oriented
    if has_image:
        for keyword in INTENT_PATTERNS["PAYMENT_DELIVERY"]:
            if keyword in text_lower:
                return None
        return "PHOTO_IDENT"

    return None


def _score_keyword_candidates(text_lower: str, text_len: int, top_k: int) -> list[tuple[str, float]]:
    """Collect top-k intent candidates with hit-based scores."""
    scored: list[tuple[str, float]] = []

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
        hits = sum(1 for keyword in keywords if keyword in text_lower)
        if hits > 0:
            scored.append((intent, float(hits)))

    scored.sort(key=lambda item: item[1], reverse=True)
    candidates = [intent for intent, _score in scored]

    if "DISCOVERY_OR_QUESTION" not in candidates:
        scored.append(("DISCOVERY_OR_QUESTION", 0.05))
    if "THANKYOU_SMALLTALK" not in candidates:
        scored.append(("THANKYOU_SMALLTALK", 0.01))
    if "GREETING_ONLY" not in candidates:
        scored.append(("GREETING_ONLY", 0.01))

    return scored[:top_k]


async def intent_detection_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Detect intent from user input for smart routing.

    This runs BEFORE LLM to enable conditional edges.
    Fast and lightweight - no API calls.
    """
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    user_id = state.get("metadata", {}).get("user_id", "")

    memory_context = await MemoryGateway.fetch_context(session_id, user_id=user_id)
    if memory_context.get("storage_available"):
        state = {
            **state,
            "memory_profile": memory_context.get("profile"),
            "memory_facts": memory_context.get("facts", []),
            "memory_context_prompt": memory_context.get("prompt"),
        }

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
    intent_confidence = selection["confidence"]
    intent_ambiguous = selection["ambiguous_flag"]
    intent_reason = selection["reason"]

    logger.debug(
        "Intent detected: %s, deferred=%s, candidates=%s (text=%s, has_image=%s, state=%s)",
        detected_intent,
        deferred_intents,
        intent_candidates,
        user_content[:50] if user_content else "",
        has_image,
        metadata.current_state.value,
    )

    await upsert_facts_from_text(session_id=session_id, user_id=user_id, text=str(user_content or ""))

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
            "intent_confidence": intent_confidence,
            "intent_ambiguous": intent_ambiguous,
            "intent_reason": intent_reason,
        },
        "step_number": state.get("step_number", 0) + 1,
    }
