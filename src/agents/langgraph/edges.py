"""
Routing Edges - Conditional flow control.
These functions determine WHERE the graph goes next.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from src.core.state_machine import State

from .nodes.intent import get_intent_patterns
from .nodes.utils import extract_user_message
from .state_prompts import detect_simple_intent


logger = logging.getLogger(__name__)


MasterRoute = Literal[
    "moderation",
    "intent",
    "agent",
    "offer",
    "payment",
    "upsell",
    "escalation",
    "crm_error",
    "end",
]
ModerationRoute = Literal["intent", "escalation"]
IntentRoute = Literal["vision", "agent", "offer", "payment", "escalation"]
ValidationRoute = Literal["agent", "escalation", "end"]
AgentRoute = Literal["validation", "offer", "end"]
OfferRoute = Literal["payment", "validation", "end"]


_DEFAULT_PHASE_ROUTES: dict[str, MasterRoute] = {
    "DISCOVERY": "agent",
    "VISION_DONE": "agent",
    "SIZE_COLOR_DONE": "offer",
    "WAITING_FOR_DELIVERY_DATA": "agent",
    "WAITING_FOR_PAYMENT_METHOD": "payment",
    "WAITING_FOR_PAYMENT_PROOF": "payment",
    "UPSELL_OFFERED": "upsell",
    "COMPLAINT": "escalation",
    "OUT_OF_DOMAIN": "escalation",
}


def _route_debug(
    *,
    session_id: str,
    current_phase: str,
    detected_intent: str | None,
    destination: str,
    reason: str,
) -> None:
    logger.info(
        "[SESSION %s] route=%s phase=%s intent=%s reason=%s",
        session_id,
        destination,
        current_phase,
        detected_intent,
        reason,
    )


def _resolve_phase_route(
    dialog_phase: str,
    detected_intent: str | None,
    user_message: str,
) -> tuple[MasterRoute | None, str | None]:
    if dialog_phase in {"WAITING_FOR_SIZE", "WAITING_FOR_COLOR"}:
        if detected_intent == "PAYMENT_DELIVERY":
            return "payment", f"{dialog_phase} but got confirmation"
        return "agent", dialog_phase

    if dialog_phase == "OFFER_MADE":
        if detected_intent == "PAYMENT_DELIVERY":
            return "payment", "OFFER_MADE + PAYMENT_DELIVERY"

        confirmation_keywords = get_intent_patterns().get("CONFIRMATION", [])
        msg_lower = user_message.lower() if user_message else ""
        for keyword in confirmation_keywords:
            if keyword in msg_lower:
                return "payment", f"OFFER_MADE + confirmation: '{keyword}'"

        return "agent", "OFFER_MADE clarifying question"

    if dialog_phase == "COMPLETED":
        if detected_intent == "THANKYOU_SMALLTALK":
            return "end", "COMPLETED + thanks"
        return "moderation", "COMPLETED but new query"

    if dialog_phase in _DEFAULT_PHASE_ROUTES:
        return _DEFAULT_PHASE_ROUTES[dialog_phase], dialog_phase

    return None, None


# =============================================================================
# MASTER ROUTER (Turn-Based State Machine)
# =============================================================================


def master_router(state: dict[str, Any]) -> MasterRoute:
    """
    Master router - checks dialog_phase to determine where to continue.
    """
    dialog_phase = state.get("dialog_phase", "INIT")
    metadata = state.get("metadata", {}) or {}
    session_id = state.get("session_id") or metadata.get("session_id") or "?"
    trace_id = state.get("trace_id") or metadata.get("trace_id") or ""
    has_image = state.get("has_image", False) or metadata.get("has_image", False)

    user_message = extract_user_message(state.get("messages", []))
    detected_intent = detect_simple_intent(user_message) if user_message else None

    logger.info(
        "[SESSION %s] master_router: trace_id=%s phase=%s has_image=%s intent=%s msg='%s'",
        session_id,
        trace_id,
        dialog_phase,
        has_image,
        detected_intent,
        user_message[:50] if user_message else "",
    )

    # =========================================================================
    # SPECIAL CASES (highest priority)
    # =========================================================================
    if has_image:
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="moderation",
            reason="new image detected",
        )
        return "moderation"

    if detected_intent == "COMPLAINT":
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="escalation",
            reason="COMPLAINT detected in message",
        )
        return "escalation"

    if dialog_phase == "CRM_ERROR_HANDLING":
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="crm_error",
            reason="CRM_ERROR_HANDLING",
        )
        return "crm_error"

    # =========================================================================
    # RULE 3: Route based on dialog_phase + intent
    # =========================================================================
    destination, reason = _resolve_phase_route(
        dialog_phase=dialog_phase,
        detected_intent=detected_intent,
        user_message=user_message or "",
    )
    if destination:
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination=destination,
            reason=reason or "phase rule",
        )
        return destination

    # =========================================================================
    # DEFAULT: INIT or unknown - full pipeline
    # =========================================================================
    logger.info("[SESSION %s] route=moderation reason=INIT/default", session_id)
    return "moderation"


def get_master_routes() -> dict[str, str]:
    """Route map for master router - ALL possible destinations."""
    return {
        "moderation": "moderation",
        "agent": "agent",
        "offer": "offer",
        "payment": "payment",
        "upsell": "upsell",
        "escalation": "escalation",
        "crm_error": "crm_error",
        "end": "end",
    }


def route_after_moderation(state: dict[str, Any]) -> ModerationRoute:
    """
    Route after moderation check.

    - Blocked -> escalation
    - Allowed -> intent detection
    """
    if state.get("should_escalate"):
        reason = state.get("escalation_reason", "unknown")
        logger.info("Routing to escalation: %s", reason)
        return "escalation"
    return "intent"


def route_after_intent(state: dict[str, Any]) -> IntentRoute:
    """
    Route based on detected intent.

    This is the main routing decision point.
    """
    if state.get("should_escalate"):
        return "escalation"

    intent = state.get("detected_intent", "DISCOVERY_OR_QUESTION")
    current_state = state.get("current_state", State.STATE_0_INIT.value)

    logger.debug("Routing after intent: %s (state=%s)", intent, current_state)

    return _resolve_intent_route(intent, current_state, state)


def _resolve_intent_route(
    intent: str,
    current_state: str,
    state: dict[str, Any],
) -> IntentRoute:
    """Resolve routing based on intent (helper to reduce complexity)."""
    direct_routes: dict[str, IntentRoute] = {
        "PHOTO_IDENT": "vision",
        "COMPLAINT": "escalation",
    }
    if intent in direct_routes:
        return direct_routes[intent]

    if intent == "PAYMENT_DELIVERY":
        if current_state in ["STATE_4_OFFER", "STATE_5_PAYMENT_DELIVERY"]:
            return "payment"
        if state.get("selected_products") or state.get("offered_products"):
            return "offer"
        return "agent"

    if intent in ["SIZE_HELP", "COLOR_HELP"] and state.get("selected_products"):
        return "offer"

    return "agent"


def route_after_validation(state: dict[str, Any]) -> ValidationRoute:
    """
    Route after validation check.

    This enables the SELF-CORRECTION LOOP.
    """
    errors = state.get("validation_errors", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if not errors:
        return "end"

    if retry_count >= max_retries:
        logger.warning(
            "Max retries (%d) reached, escalating. Errors: %s",
            max_retries,
            errors[:2],
        )
        return "escalation"

    logger.info("Validation failed (attempt %d), retrying", retry_count)
    return "agent"


def should_retry(state: dict[str, Any]) -> bool:
    """Check if we should retry after validation failure."""
    errors = state.get("validation_errors", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if not errors:
        return False
    return not retry_count >= max_retries


def route_after_agent(state: dict[str, Any]) -> AgentRoute:
    """
    Route after agent response.

    Always go through validation first for quality control.
    """
    if state.get("last_error"):
        return "validation"

    if state.get("selected_products"):
        current_state = state.get("current_state", "")
        if current_state in ["STATE_4_OFFER", "STATE_5_PAYMENT_DELIVERY"]:
            return "validation"
        return "offer"

    return "validation"


def route_after_offer(state: dict[str, Any]) -> OfferRoute:
    """Route after offer presented."""
    intent = state.get("detected_intent", "")
    if intent == "PAYMENT_DELIVERY":
        return "payment"
    return "validation"


def route_after_vision(state: dict[str, Any]) -> Literal["offer", "agent", "validation"]:
    """Route after vision processing."""
    if state.get("selected_products"):
        return "offer"
    if state.get("last_error"):
        return "validation"
    return "agent"


def route_after_payment(state: dict[str, Any]) -> Literal["upsell", "end", "validation"]:
    """
    Route after payment processing.

    Note: Payment node returns Command, so this is rarely used directly.
    """
    if state.get("human_approved"):
        return "upsell"
    if state.get("validation_errors"):
        return "validation"
    return "end"


# =============================================================================
# ROUTE MAP BUILDERS (for graph.add_conditional_edges)
# =============================================================================


def get_moderation_routes() -> dict[str, str]:
    """Get route map for moderation node."""
    return {
        "intent": "intent",
        "escalation": "escalation",
    }


def get_intent_routes() -> dict[str, str]:
    """Get route map for intent node."""
    return {
        "vision": "vision",
        "agent": "agent",
        "offer": "offer",
        "payment": "payment",
        "escalation": "escalation",
    }


def get_validation_routes() -> dict[str, str]:
    """Get route map for validation node."""
    return {
        "agent": "agent",
        "escalation": "escalation",
        "end": "end",
    }


def get_agent_routes() -> dict[str, str]:
    """Get route map for agent node."""
    return {
        "validation": "validation",
        "offer": "offer",
        "end": "end",
    }
