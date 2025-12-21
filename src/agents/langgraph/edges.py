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

<<<<<<< Updated upstream
=======
from .nodes.intent import get_intent_patterns
from .nodes.utils import extract_user_message

# Import for intent detection
from .state_prompts import detect_simple_intent

>>>>>>> Stashed changes

logger = logging.getLogger(__name__)


# Type aliases for routing destinations
ModerationRoute = Literal["intent", "escalation"]
IntentRoute = Literal["vision", "agent", "offer", "payment", "escalation"]
ValidationRoute = Literal["agent", "escalation", "end"]
AgentRoute = Literal["validation", "offer", "end"]
OfferRoute = Literal["payment", "validation", "end"]


<<<<<<< Updated upstream
=======
# =============================================================================
# MASTER ROUTER (Turn-Based State Machine)
# =============================================================================
# This is the ENTRY POINT router that checks dialog_phase
# to continue the conversation from where we left off.
#
# ПОВНА МАПА ФАЗ → НОДІВ (як в n8n state machine):
#
# INIT                      → moderation (повний pipeline)
# DISCOVERY                 → agent (STATE_1: збір контексту)
# VISION_DONE               → agent (STATE_2→3: уточнення після фото)
# WAITING_FOR_SIZE          → agent (STATE_3: чекаємо зріст)
# WAITING_FOR_COLOR         → agent (STATE_3: чекаємо колір)
# SIZE_COLOR_DONE           → offer (STATE_4: готові до пропозиції)
# OFFER_MADE                → payment (STATE_4→5: "Беру" → оплата)
# WAITING_FOR_DELIVERY_DATA → payment (STATE_5: збір даних)
# WAITING_FOR_PAYMENT_METHOD→ payment (STATE_5: спосіб оплати)
# WAITING_FOR_PAYMENT_PROOF → payment (STATE_5: скрін оплати)
# UPSELL_OFFERED            → upsell (STATE_6: відповідь на допродаж)
# COMPLETED                 → end (STATE_7: завершено)
# COMPLAINT                 → escalation (STATE_8)
# OUT_OF_DOMAIN             → escalation (STATE_9)
# =============================================================================


def master_router(state: dict[str, Any]) -> MasterRoute:
    """
    Master router - checks dialog_phase to determine where to continue.

    QUALITY IMPLEMENTATION:
    - Враховує dialog_phase
    - Аналізує intent з повідомлення користувача
    - Правильно маршрутизує на основі контексту
    """
    dialog_phase = state.get("dialog_phase", "INIT")
    metadata = state.get("metadata", {}) or {}
    session_id = state.get("session_id") or metadata.get("session_id") or "?"
    trace_id = state.get("trace_id") or metadata.get("trace_id") or ""
    # Prefer top-level flag, but fall back to metadata (photo handler writes there)
    has_image = state.get("has_image", False) or metadata.get("has_image", False)

    # QUALITY: Отримуємо останнє повідомлення для аналізу intent
    user_message = extract_user_message(state.get("messages", []))
    detected_intent = detect_simple_intent(user_message) if user_message else None

    logger.info(
        " [SESSION %s] Master router: trace_id=%s phase=%s has_image=%s intent=%s msg='%s'",
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

    # CRM ERROR HANDLING - route to crm_error node
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

    # STATE_1: Discovery - збір контексту (зріст, тип речі)
    if dialog_phase == "DISCOVERY":
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="agent",
            reason="DISCOVERY",
        )
        return "agent"

    # STATE_2→3: Vision done - потрібно уточнення
    if dialog_phase == "VISION_DONE":
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="agent",
            reason="VISION_DONE",
        )
        return "agent"

    # STATE_3: Waiting for size
    if dialog_phase == "WAITING_FOR_SIZE":
        # Якщо юзер каже "беру" замість розміру - йдемо в payment
        if detected_intent == "PAYMENT_DELIVERY":
            _route_debug(
                session_id=session_id,
                current_phase=dialog_phase,
                detected_intent=detected_intent,
                destination="payment",
                reason="WAITING_FOR_SIZE but got confirmation",
            )
            return "payment"
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="agent",
            reason="WAITING_FOR_SIZE",
        )
        return "agent"

    # STATE_3: Waiting for color
    if dialog_phase == "WAITING_FOR_COLOR":
        if detected_intent == "PAYMENT_DELIVERY":
            _route_debug(
                session_id=session_id,
                current_phase=dialog_phase,
                detected_intent=detected_intent,
                destination="payment",
                reason="WAITING_FOR_COLOR but got confirmation",
            )
            return "payment"
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="agent",
            reason="WAITING_FOR_COLOR",
        )
        return "agent"

    # STATE_3→4: Size and color ready
    if dialog_phase == "SIZE_COLOR_DONE":
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="offer",
            reason="SIZE_COLOR_DONE",
        )
        return "offer"

    # STATE_4: Offer made - чекаємо "Беру" або підтвердження
    if dialog_phase == "OFFER_MADE":
        # User confirms order ("беру", "да", "так") → payment flow
        if detected_intent == "PAYMENT_DELIVERY":
            _route_debug(
                session_id=session_id,
                current_phase=dialog_phase,
                detected_intent=detected_intent,
                destination="payment",
                reason="OFFER_MADE + PAYMENT_DELIVERY",
            )
            return "payment"

        # Check confirmation keywords directly (да, так, ок, беру, etc.)
        confirmation_keywords = get_intent_patterns().get("CONFIRMATION", [])
        msg_lower = user_message.lower() if user_message else ""
        for keyword in confirmation_keywords:
            if keyword in msg_lower:
                _route_debug(
                    session_id=session_id,
                    current_phase=dialog_phase,
                    detected_intent=detected_intent,
                    destination="payment",
                    reason=f"OFFER_MADE + confirmation: '{keyword}'",
                )
                return "payment"

        # User asks clarifying question → agent handles it
        logger.info("🔀 [SESSION %s] → agent (OFFER_MADE, clarifying)", session_id)
        return "agent"

    # STATE_5: Collecting delivery data → use AGENT to extract name/phone/city
    # Payment node uses interrupt() for HITL which blocks - only use it after data is collected
    if dialog_phase == "WAITING_FOR_DELIVERY_DATA":
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="agent",
            reason="WAITING_FOR_DELIVERY_DATA (collecting data)",
        )
        return "agent"

    # STATE_5: Waiting for payment method
    if dialog_phase == "WAITING_FOR_PAYMENT_METHOD":
        # Payment sub-flow: спосіб оплати обробляється в payment node
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="payment",
            reason="WAITING_FOR_PAYMENT_METHOD",
        )
        return "payment"

    # STATE_5: Waiting for payment proof
    if dialog_phase == "WAITING_FOR_PAYMENT_PROOF":
        # Payment sub-flow: підтвердження оплати обробляється в payment node
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="payment",
            reason="WAITING_FOR_PAYMENT_PROOF",
        )
        return "payment"

    # STATE_6: Upsell offered
    if dialog_phase == "UPSELL_OFFERED":
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="upsell",
            reason="UPSELL_OFFERED",
        )
        return "upsell"

    # STATE_7: Completed - but user wrote again
    if dialog_phase == "COMPLETED":
        # QUALITY: Якщо юзер пише після COMPLETED - новий діалог
        if detected_intent == "THANKYOU_SMALLTALK":
            _route_debug(
                session_id=session_id,
                current_phase=dialog_phase,
                detected_intent=detected_intent,
                destination="end",
                reason="COMPLETED + thanks",
            )
            return "end"
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="moderation",
            reason="COMPLETED but new query",
        )
        return "moderation"

    # STATE_8: Complaint
    if dialog_phase == "COMPLAINT":
        logger.info("🔀 [SESSION %s] → escalation (COMPLAINT)", session_id)
        return "escalation"

    # STATE_9: Out of domain
    if dialog_phase == "OUT_OF_DOMAIN":
        logger.info("🔀 [SESSION %s] → escalation (OUT_OF_DOMAIN)", session_id)
        return "escalation"

    # =========================================================================
    # DEFAULT: INIT or unknown - full pipeline
    # =========================================================================
    logger.info("🔀 [SESSION %s] → moderation (INIT/default)", session_id)
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


>>>>>>> Stashed changes
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
