"""
Intent Router.
==============
Routing logic after intent detection.
"""

from typing import Dict, Literal
import logging
from src.core.state_machine import State
from src.agents.langgraph.routers.base import safe_router, StateSchema
from src.agents.langgraph.routers.enums import Route

logger = logging.getLogger(__name__)


def get_intent_routes() -> Dict[str, str]:
    return {
        Route.VISION.value: "vision",
        Route.AGENT.value: "agent",
        Route.OFFER.value: "offer",
        Route.PAYMENT.value: "payment",
        Route.ESCALATION.value: "escalation",
        Route.DISAMBIGUATION.value: "agent",
        Route.END.value: "end",
    }


@safe_router
def route_after_intent(
    state: StateSchema,
) -> Literal["vision", "agent", "offer", "payment", "escalation", "end"]:
    """
    Decide where to go based on detected intent and current state.
    """
    intent = state.detected_intent
    current_state = state.state_enum
    has_image = state.has_image

    # 1. Escalation / Complaint
    if state.should_escalate or intent == "ESCALATION" or intent == "COMPLAINT":
        return Route.ESCALATION

    # 1.5 Ambiguous intent -> clarification/disambiguation node (agent)
    if intent == "AMBIGUOUS":
        return Route.DISAMBIGUATION

    # 2. Greeting / Smalltalk -> Agent
    if intent in ("GREETING_ONLY", "THANKYOU_SMALLTALK"):
        return Route.AGENT

    # 2.5 PHOTO_IDENT is a hard signal for vision even if has_image flag
    # was dropped in a synthetic/test payload.
    if intent == "PHOTO_IDENT":
        return Route.VISION

    # 3. Vision Flow (Image present)
    # Priority: If image is present, usually go to vision, UNLESS in payment flow
    if has_image:
        if current_state == State.STATE_5_PAYMENT_DELIVERY:
            # Check context: is it payment proof?
            # Intent logic should have handled this, but we double check
            if intent == "PAYMENT_DELIVERY":
                return Route.PAYMENT

        # Fallback: if we are here with an image, and it's not payment, default to vision
        return Route.VISION

    # 4. Payment Flow
    if intent == "PAYMENT_DELIVERY":
        # SAFEGUARD: Only route to payment if we are already in payment state
        # OR if we have products selected.
        if current_state == State.STATE_5_PAYMENT_DELIVERY:
            return Route.PAYMENT

        if current_state == State.STATE_4_OFFER:
            return Route.PAYMENT

        # If user says "buy" but no products?
        if state.selected_products or state.offered_products:
            return Route.OFFER

        return Route.AGENT

    # 5. Offer confirmation
    if current_state == State.STATE_4_OFFER and intent == "CONFIRMATION":
        return Route.PAYMENT

    # 6. If size/color clarification arrives with products selected, continue offer flow.
    if intent in ("SIZE_HELP", "COLOR_HELP") and (state.selected_products or state.offered_products):
        return Route.OFFER

    # 7. Default: Agent
    return Route.AGENT
