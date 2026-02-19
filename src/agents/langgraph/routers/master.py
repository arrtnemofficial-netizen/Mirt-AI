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


def _route_offer_payment_policy(state: StateSchema, user_msg: str) -> tuple[Route, str, str | None]:
    """
    Policy router for STATE_4_OFFER and STATE_5_PAYMENT_DELIVERY.

    Priority:
    1) dialog_phase + structured state flags
    2) intent detection
    3) keyword fallback
    """
    current_state = state.state_enum
    metadata = state.metadata or {}
    msg_lower = (user_msg or "").lower()

    # 1) Phase policy + structured flags (highest priority)
    if current_state == State.STATE_4_OFFER:
        if state.dialog_phase == "WAITING_FOR_DELIVERY_DATA":
            return Route.PAYMENT, "route_reason=phase_policy phase=WAITING_FOR_DELIVERY_DATA", None

        if metadata.get("user_confirmed") or metadata.get("awaiting_payment_confirmation"):
            return Route.PAYMENT, "route_reason=phase_policy flag=user_confirmed", None

    if current_state == State.STATE_5_PAYMENT_DELIVERY:
        if state.dialog_phase == "WAITING_FOR_DELIVERY_DATA":
            if metadata.get("payment_request_data_sent"):
                return (
                    Route.AGENT,
                    "route_reason=phase_policy phase=WAITING_FOR_DELIVERY_DATA flag=payment_request_data_sent",
                    None,
                )
            return Route.PAYMENT, "route_reason=phase_policy phase=WAITING_FOR_DELIVERY_DATA", None

        if state.dialog_phase in {"WAITING_FOR_PAYMENT_METHOD", "WAITING_FOR_PAYMENT_PROOF", "UPSELL_OFFERED"}:
            return Route.PAYMENT, f"route_reason=phase_policy phase={state.dialog_phase}", None

    # 2) Intent result
    detected_intent = detect_intent_from_text(user_msg, state.has_image, current_state.value)
    if current_state == State.STATE_4_OFFER:
        if detected_intent == "PAYMENT_DELIVERY":
            return Route.PAYMENT, "route_reason=intent intent=PAYMENT_DELIVERY", detected_intent
        return Route.AGENT, f"route_reason=intent intent={detected_intent}", detected_intent

    if current_state == State.STATE_5_PAYMENT_DELIVERY:
        if detected_intent in {"PRODUCT_CATEGORY", "REQUEST_PHOTO", "DISCOVERY_OR_QUESTION", "SIZE_HELP", "COLOR_HELP"}:
            return Route.AGENT, f"route_reason=intent intent={detected_intent}", detected_intent
        if detected_intent == "PAYMENT_DELIVERY":
            return Route.PAYMENT, "route_reason=intent intent=PAYMENT_DELIVERY", detected_intent

    # 3) Keyword fallback (last resort only)
    if current_state == State.STATE_4_OFFER and any(
        keyword in msg_lower for keyword in INTENT_PATTERNS.get("CONFIRMATION", [])
    ):
        return Route.PAYMENT, "route_reason=keyword_fallback keyword=confirmation", None

    if current_state == State.STATE_5_PAYMENT_DELIVERY and any(
        keyword in msg_lower for keyword in INTENT_PATTERNS.get("PAYMENT_DELIVERY", [])
    ):
        return Route.PAYMENT, "route_reason=keyword_fallback keyword=payment_delivery", None

    # Safe defaults by state
    if current_state == State.STATE_4_OFFER:
        return Route.AGENT, "route_reason=keyword_fallback default=offer_question", None
    return Route.PAYMENT, "route_reason=keyword_fallback default=payment_flow", None

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
        user_msg = extract_user_message(state.messages)
        if not user_msg:
            _route_debug(session_id, current_state.value, "offer", "route_reason=phase_policy no_user_message")
            return Route.OFFER

        target_route, reason, intent = _route_offer_payment_policy(state, user_msg)
        _route_debug(session_id, current_state.value, target_route.value, reason, intent)
        return target_route

    if current_state == State.STATE_5_PAYMENT_DELIVERY:
        user_msg = extract_user_message(state.messages)
        target_route, reason, intent = _route_offer_payment_policy(state, user_msg)
        _route_debug(session_id, current_state.value, target_route.value, reason, intent)
        return target_route

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
