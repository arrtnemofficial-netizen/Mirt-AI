"""
Master Router.
==============
Top-level routing logic for the conversation.
Determines entry points based on FSM state.
"""

from typing import Dict, Literal
import logging

from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.agents.langgraph.routers.base import safe_router, StateSchema
from src.agents.langgraph.routers.enums import Route
from src.agents.langgraph.nodes.utils import extract_user_message
from src.agents.langgraph.rules.photo_purpose import determine_photo_purpose
from src.agents.langgraph.nodes.intent import detect_intent_from_text, INTENT_PATTERNS

logger = logging.getLogger(__name__)

def get_master_routes() -> Dict[str, str]:
    """Map routing outcomes to graph nodes."""
    return {
        Route.MODERATION.value: "moderation",
        Route.AGENT.value: "agent",
        Route.OFFER.value: "offer",
        Route.PAYMENT.value: "payment",
        Route.UPSELL.value: "upsell",
        Route.END.value: "end",
        Route.ESCALATION.value: "escalation",
    }

def _route_debug(
    session_id: str,
    current_state: str,
    destination: str,
    reason: str,
    intent: str | None = None,
) -> None:
    """Helper for structured logging of routing decisions."""
    if settings.DEBUG_TRACE_LOGS:
        debug_log.routing_decision(
            session_id=session_id,
            current_phase=current_state, # mapping state to phase param for now
            detected_intent=intent,
            destination=destination,
            reason=reason,
        )
    else:
        logger.info(
            "🔀 [SESSION %s] %s -> %s (%s)",
            session_id,
            current_state,
            destination,
            reason,
        )

@safe_router
def master_router(state: StateSchema) -> Literal["moderation", "agent", "offer", "payment", "upsell", "end", "escalation"]:
    """
    Main entry router based on current FSM state.
    Refined logic to handle data collection vs processing.
    """
    session_id = state.session_id
    current_state = state.state_enum
    has_image = state.has_image

    # 1. Image Handling (Critical: Receipt vs Product)
    if has_image:
        state_dict = state.to_dict()
        user_msg = extract_user_message(state.messages)

        photo_purpose, reason = determine_photo_purpose(state_dict, user_msg)

        if photo_purpose == "transactional":
            _route_debug(session_id, current_state.value, "payment", f"Photo purpose: {photo_purpose}")
            return Route.PAYMENT

        elif photo_purpose == "product_ident":
            _route_debug(session_id, current_state.value, "moderation", f"Photo purpose: {photo_purpose}")
            return Route.MODERATION

        else:
            _route_debug(session_id, current_state.value, "agent", f"Photo purpose: {photo_purpose}")
            return Route.AGENT

    # 2. State-based routing
    if current_state == State.STATE_0_INIT:
        _route_debug(session_id, current_state.value, "moderation", "INIT")
        return Route.MODERATION

    if current_state in (State.STATE_1_DISCOVERY, State.STATE_2_VISION, State.STATE_3_SIZE_COLOR):
        _route_debug(session_id, current_state.value, "agent", "Discovery/Vision/SizeColor")
        return Route.AGENT

    if current_state == State.STATE_4_OFFER:
        # In OFFER state, we need to distinguish between:
        # A) User confirms ("I'll take it") -> Payment
        # B) User asks questions ("Is it wool?") -> Agent
        user_msg = extract_user_message(state.messages)
        if user_msg:
             # Fast intent check
             intent = detect_intent_from_text(user_msg, has_image, current_state.value)

             if intent == "PAYMENT_DELIVERY":
                 _route_debug(session_id, current_state.value, "payment", "Intent: PAYMENT_DELIVERY")
                 return Route.PAYMENT

             # Simple keyword check for confirmation
             msg_lower = user_msg.lower()
             if any(k in msg_lower for k in INTENT_PATTERNS.get("CONFIRMATION", [])):
                 _route_debug(session_id, current_state.value, "payment", "Keyword: Confirmation")
                 return Route.PAYMENT

             # If not payment/confirmation, let Agent handle questions
             _route_debug(session_id, current_state.value, "agent", "Questions in OFFER state")
             return Route.AGENT

        # Fallback if no message (rare) or unclear
        return Route.OFFER

    if current_state == State.STATE_5_PAYMENT_DELIVERY:
        # In PAYMENT state, we need to distinguish between:
        # A) First time entering (send snippet) -> Payment Node
        # B) Data collection (Name, City) -> Agent Node (to parse and update state)
        # C) Payment method selection / Proof -> Payment Node (via Command or flow)

        # NOTE: The dialog_phase is more granular here.
        dialog_phase = state.dialog_phase

        if dialog_phase == "WAITING_FOR_DELIVERY_DATA":
            # Check if we already sent the request snippet
            if state.metadata.get("payment_request_data_sent"):
                 # Snippet sent, user is replying with data -> Agent parses it
                 _route_debug(session_id, current_state.value, "agent", "Collecting Delivery Data")
                 return Route.AGENT
            else:
                 # First time -> Payment node sends snippet
                 _route_debug(session_id, current_state.value, "payment", "Send Delivery Snippet")
                 return Route.PAYMENT

        # For other sub-phases (Method, Proof), Payment node handles it or we route there
        _route_debug(session_id, current_state.value, "payment", "Payment/Method/Proof")
        return Route.PAYMENT

    if current_state == State.STATE_6_UPSELL:
        return Route.UPSELL

    if current_state in (State.STATE_8_COMPLAINT, State.STATE_9_OOD):
        return Route.ESCALATION

    if current_state == State.STATE_7_END:
        # Restart logic
        user_msg = extract_user_message(state.messages)
        if user_msg:
             intent = detect_intent_from_text(user_msg, has_image, current_state.value)
             if intent == "THANKYOU_SMALLTALK":
                 return Route.END
             _route_debug(session_id, current_state.value, "moderation", "Restart (New Query)")
             return Route.MODERATION
        return Route.END

    # Default fallback
    _route_debug(session_id, current_state.value, "end", "Fallback")
    return Route.END
