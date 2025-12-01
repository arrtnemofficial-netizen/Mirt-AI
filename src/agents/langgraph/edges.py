"""
Routing Edges - Conditional flow control.
=========================================
These functions determine WHERE the graph goes next.
This is the "brain" of the graph - making smart decisions.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from src.core.state_machine import State


logger = logging.getLogger(__name__)


# Type aliases for routing destinations
ModerationRoute = Literal["intent", "escalation"]
IntentRoute = Literal["vision", "agent", "offer", "payment", "escalation"]
ValidationRoute = Literal["agent", "escalation", "end"]
AgentRoute = Literal["validation", "offer", "end"]
OfferRoute = Literal["payment", "validation", "end"]


def route_after_moderation(state: dict[str, Any]) -> ModerationRoute:
    """
    Route after moderation check.

    - Blocked -> escalation
    - Allowed -> intent detection
    """
    if state.get("should_escalate"):
        logger.info("Routing to escalation: moderation blocked")
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
    # Direct mappings
    direct_routes: dict[str, IntentRoute] = {
        "PHOTO_IDENT": "vision",
        "COMPLAINT": "escalation",
    }
    if intent in direct_routes:
        return direct_routes[intent]

    # Payment requires context check
    if intent == "PAYMENT_DELIVERY":
        if current_state in ["STATE_4_OFFER", "STATE_5_PAYMENT_DELIVERY"]:
            return "payment"
        if state.get("selected_products") or state.get("offered_products"):
            return "offer"
        return "agent"

    # Size/color with products -> offer
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

    # No errors -> proceed
    if not errors:
        return "end"

    # Max retries hit -> escalate
    if retry_count >= max_retries:
        logger.warning(
            "Max retries (%d) reached, escalating. Errors: %s",
            max_retries,
            errors[:2],
        )
        return "escalation"

    # Retry -> back to agent
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
    # Last error means we need validation
    if state.get("last_error"):
        return "validation"

    # Has products -> can make offer
    if state.get("selected_products"):
        current_state = state.get("current_state", "")
        # Already in offer/payment flow
        if current_state in ["STATE_4_OFFER", "STATE_5_PAYMENT_DELIVERY"]:
            return "validation"
        return "offer"

    # Default -> validate then end
    return "validation"


def route_after_offer(state: dict[str, Any]) -> OfferRoute:
    """
    Route after offer presented.
    """
    intent = state.get("detected_intent", "")

    # Payment intent -> go to payment
    if intent == "PAYMENT_DELIVERY":
        return "payment"

    # Validate response
    return "validation"


def route_after_vision(state: dict[str, Any]) -> Literal["offer", "agent", "validation"]:
    """
    Route after vision processing.
    """
    # Found products -> make offer
    if state.get("selected_products"):
        return "offer"

    # Error -> validate
    if state.get("last_error"):
        return "validation"

    # No products found -> agent for clarification
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
