"""
Intent Router.
==============
Routing logic after intent detection.
"""

from typing import Dict, Literal
import logging
from src.core.state_machine import State
from src.agents.langgraph.routers.base import safe_router, StateSchema

logger = logging.getLogger(__name__)

def get_intent_routes() -> Dict[str, str]:
    return {
        "vision": "vision",
        "agent": "agent",
        "offer": "offer",
        "payment": "payment",
        "escalation": "escalation",
        "end": "end",
    }

@safe_router
def route_after_intent(state: StateSchema) -> Literal["vision", "agent", "offer", "payment", "escalation", "end"]:
    """
    Decide where to go based on detected intent and current state.
    """
    intent = state.detected_intent
    current_state = state.state_enum
    has_image = state.has_image

    # 1. Escalation / Complaint
    if state.should_escalate or intent == "ESCALATION" or intent == "COMPLAINT":
        return "escalation"

    # 2. Greeting / Smalltalk -> Agent
    if intent in ("GREETING_ONLY", "THANKYOU_SMALLTALK"):
        return "agent"

    # 3. Vision Flow (Image present)
    # Priority: If image is present, usually go to vision, UNLESS in payment flow
    if has_image:
        if current_state == State.STATE_5_PAYMENT_DELIVERY:
            # Check context: is it payment proof?
            # Intent logic should have handled this, but we double check
            if intent == "PAYMENT_DELIVERY":
                 return "payment"

        # If intent is clearly photo ident, go to vision
        if intent == "PHOTO_IDENT":
            return "vision"

        # Fallback: if we are here with an image, and it's not payment, default to vision
        return "vision"

    # 4. Payment Flow
    if intent == "PAYMENT_DELIVERY":
        # SAFEGUARD: Only route to payment if we are already in payment state
        # OR if we have products selected.
        if current_state == State.STATE_5_PAYMENT_DELIVERY:
            return "payment"

        if current_state == State.STATE_4_OFFER:
            return "payment"

        # If user says "buy" but no products?
        if state.selected_products or state.offered_products:
            return "offer" # Go to offer to confirm/finalize before payment?
            # Original logic:
            # if products -> offer
            # if no products -> agent

        return "agent"

    # 5. Offer confirmation
    if current_state == State.STATE_4_OFFER and intent == "CONFIRMATION":
        return "payment"

    # 6. Default: Agent
    return "agent"
