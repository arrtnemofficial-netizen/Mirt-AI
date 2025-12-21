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
from src.core.state_machine import State
from src.core.prompt_registry import get_snippet_by_header


logger = logging.getLogger(__name__)


def _get_patterns(header: str) -> list[str]:
    """Get patterns from registry."""
    bubbles = get_snippet_by_header(header)
    if not bubbles:
        return []
    # Support both multi-bubble messages and multi-line keyword lists
    patterns = []
    for b in bubbles:
        patterns.extend([line.strip() for line in b.split("\n") if line.strip()])
    return patterns


def get_intent_patterns() -> dict[str, list[str]]:
    """Get all intent patterns from registry."""
    return {
        "PAYMENT_DELIVERY": _get_patterns("INTENT_PATTERN_PAYMENT_DELIVERY"),
        "CONFIRMATION": _get_patterns("INTENT_PATTERN_CONFIRMATION"),
        "PRODUCT_NAMES": _get_patterns("INTENT_PATTERN_PRODUCT_NAMES"),
        "PRODUCT_CATEGORY": _get_patterns("INTENT_PATTERN_PRODUCT_CATEGORY"),
        "SIZE_HELP": _get_patterns("INTENT_PATTERN_SIZE_HELP"),
        "COLOR_HELP": _get_patterns("INTENT_PATTERN_COLOR_HELP"),
        "COMPLAINT": _get_patterns("INTENT_PATTERN_COMPLAINT"),
        "REQUEST_PHOTO": _get_patterns("INTENT_PATTERN_REQUEST_PHOTO"),
        "DISCOVERY_OR_QUESTION": _get_patterns("INTENT_PATTERN_DISCOVERY"),
        "GREETING_ONLY": _get_patterns("INTENT_PATTERN_GREETING"),
        "THANKYOU_SMALLTALK": _get_patterns("INTENT_PATTERN_THANKYOU"),
    }


def detect_intent_from_text(
    text: str,
    has_image: bool,
    current_state: str,
) -> str:
    """Quick intent detection based on keywords and context."""
    text_lower = text.lower().strip()
    patterns = get_intent_patterns()

    # Special cases first
    special = _check_special_cases(text_lower, has_image, current_state, patterns)
    if special:
        return special

    # Keyword matching in priority order
    return _match_keywords(text_lower, len(text), patterns)


def _check_special_cases(text_lower: str, has_image: bool, current_state: str, patterns: dict) -> str | None:
    """Check special cases before keyword matching."""
    if not text_lower and has_image:
        return "PHOTO_IDENT"

    if current_state == "STATE_4_OFFER":
        for keyword in patterns["PAYMENT_DELIVERY"]:
            if keyword in text_lower:
                return "PAYMENT_DELIVERY"
        for keyword in patterns["CONFIRMATION"]:
            if keyword in text_lower:
                return "PAYMENT_DELIVERY"
        for keyword in patterns["PRODUCT_NAMES"]:
            if keyword in text_lower:
                return "PAYMENT_DELIVERY"

    if current_state == "STATE_5_PAYMENT_DELIVERY":
        for keyword in patterns["COMPLAINT"]:
            if keyword in text_lower:
                return None
        return "PAYMENT_DELIVERY"

    if has_image:
        for keyword in patterns["PAYMENT_DELIVERY"]:
            if keyword in text_lower:
                return None
        return "PHOTO_IDENT"

    return None


def _match_keywords(text_lower: str, text_len: int, patterns: dict) -> str:
    """Match keywords in priority order."""
    priority_intents = [
        "PAYMENT_DELIVERY",
        "COMPLAINT",
        "SIZE_HELP",
        "COLOR_HELP",
        "REQUEST_PHOTO",
        "PRODUCT_CATEGORY",
    ]

    for intent in priority_intents:
        for keyword in patterns.get(intent, []):
            if keyword in text_lower:
                return intent

    if text_len < 30:
        for keyword in patterns["GREETING_ONLY"]:
            if keyword in text_lower:
                return "GREETING_ONLY"

    for keyword in patterns["DISCOVERY_OR_QUESTION"]:
        if keyword in text_lower:
            return "DISCOVERY_OR_QUESTION"

    return "DISCOVERY_OR_QUESTION"


async def intent_detection_node(state: dict[str, Any]) -> dict[str, Any]:
    """Detect intent from user input for smart routing."""
    dialog_phase = state.get("dialog_phase", "")
    reset_for_new = dialog_phase == "COMPLETED"

    metadata = state.get("metadata", {})
    has_image_early = state.get("has_image", False) or metadata.get("has_image", False)

    if has_image_early:
        return {
            "detected_intent": "PHOTO_IDENT",
            "has_image": True,
            "image_url": metadata.get("image_url"),
            "metadata": {**metadata, "has_image": True},
            "step_number": state.get("step_number", 0) + 1,
        }

    if state.get("should_escalate"):
        return {
            "detected_intent": "ESCALATION",
            "step_number": state.get("step_number", 0) + 1,
        }

    metadata = validate_input_metadata(state.get("metadata", {}))
    from .utils import extract_user_message
    user_content = extract_user_message(state.get("messages", []))

    has_image = metadata.has_image or bool(metadata.image_url)
    image_url = metadata.image_url

    detected_intent = detect_intent_from_text(
        text=user_content,
        has_image=has_image,
        current_state=metadata.current_state.value,
    )

    reset_now = reset_for_new and detected_intent != "THANKYOU_SMALLTALK"
    update = {
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
    if reset_now:
        update.update({
            "current_state": State.STATE_0_INIT.value,
            "dialog_phase": "INIT",
            "selected_products": [],
            "offered_products": [],
            "metadata": {
                **state.get("metadata", {}),
                "has_image": has_image,
                "image_url": image_url,
                "current_state": State.STATE_0_INIT.value,
                "intent": detected_intent,
                "upsell_flow_active": False,
                "upsell_base_products": [],
            },
        })
    return update
