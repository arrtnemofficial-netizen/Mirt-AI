"""Thin adapter for intent detection service."""

from __future__ import annotations

import logging
from typing import Any

from src.agents.langgraph.intent.service import (
    INTENT_PATTERNS,
    detect_intent_legacy,
    intent_detection_service,
)
from src.conf.config import settings
from src.core.input_validator import validate_input_metadata

logger = logging.getLogger(__name__)


def detect_intent_from_text(text: str, has_image: bool, current_state: str) -> str:
    """Backwards compatible API for deterministic intent label detection."""
    return detect_intent_legacy(text=text, has_image=has_image, current_state=current_state)


async def intent_detection_node(state: dict[str, Any]) -> dict[str, Any]:
    metadata = state.get("metadata", {})
    has_image_early = state.get("has_image", False) or metadata.get("has_image", False)

    from .utils import extract_user_message

    user_content_early = extract_user_message(state.get("messages", []))

    if has_image_early:
        from src.agents.langgraph.rules.photo_purpose import determine_photo_purpose

        photo_purpose, reason = determine_photo_purpose(state, user_content_early)
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

            result = intent_detection_service.detect(
                text=user_content_early,
                has_image=True,
                current_state=state.get("current_state", "STATE_0_INIT"),
            )
            return {
                "detected_intent": intent,
                "has_image": True,
                "image_url": metadata.get("image_url"),
                "metadata": {
                    **metadata,
                    "has_image": True,
                    "image_context": image_context,
                    "intent_result_v1": result.model_dump(),
                },
                "step_number": state.get("step_number", 0) + 1,
            }

        if photo_purpose == "transactional":
            return {
                "detected_intent": "PAYMENT_DELIVERY",
                "has_image": True,
                "image_url": metadata.get("image_url"),
                "metadata": {
                    **metadata,
                    "has_image": True,
                    "image_context": "payment",
                },
                "step_number": state.get("step_number", 0) + 1,
            }

        return {
            "detected_intent": "DISCOVERY_OR_QUESTION",
            "has_image": True,
            "image_url": metadata.get("image_url"),
            "metadata": {
                **metadata,
                "has_image": True,
                "image_context": "ongoing_conversation",
            },
            "step_number": state.get("step_number", 0) + 1,
        }

    if state.get("should_escalate"):
        return {"detected_intent": "ESCALATION", "step_number": state.get("step_number", 0) + 1}

    validated_metadata = validate_input_metadata(state.get("metadata", {}))
    user_content = extract_user_message(state.get("messages", []))

    has_image = validated_metadata.has_image or bool(validated_metadata.image_url)
    image_url = validated_metadata.image_url
    current_state = validated_metadata.current_state.value

    legacy_intent = detect_intent_legacy(
        text=user_content,
        has_image=has_image,
        current_state=current_state,
    )
    service_result = intent_detection_service.detect(
        text=user_content,
        has_image=has_image,
        current_state=current_state,
    )

    use_service = settings.INTENT_SERVICE_V1_ENABLED
    shadow_enabled = settings.INTENT_SERVICE_V1_SHADOW

    detected_intent = service_result.primary_intent if use_service else legacy_intent
    metadata_out: dict[str, Any] = {
        **state.get("metadata", {}),
        "has_image": has_image,
        "image_url": image_url,
        "intent_result_v1": service_result.model_dump(),
    }

    if shadow_enabled:
        metadata_out["intent_shadow"] = {
            "legacy_intent": legacy_intent,
            "service_primary_intent": service_result.primary_intent,
            "match": legacy_intent == service_result.primary_intent,
        }

    logger.debug(
        "Intent detected=%s legacy=%s service=%s shadow=%s",
        detected_intent,
        legacy_intent,
        service_result.primary_intent,
        shadow_enabled,
    )

    return {
        "detected_intent": detected_intent,
        "has_image": has_image,
        "image_url": image_url,
        "metadata": metadata_out,
        "step_number": state.get("step_number", 0) + 1,
    }
