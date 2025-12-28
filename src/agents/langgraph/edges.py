"""
Routing Edges - Conditional flow control.
=========================================
These functions determine WHERE the graph goes next.
This is the "brain" of the graph - making smart decisions.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State

from .nodes.intent import INTENT_PATTERNS
from .nodes.utils import extract_user_message

# Import for intent detection
from .state_prompts import detect_simple_intent


logger = logging.getLogger(__name__)


def _route_debug(
    *,
    session_id: str,
    current_phase: str,
    detected_intent: str | None,
    destination: str,
    reason: str,
) -> None:
    if settings.DEBUG_TRACE_LOGS:
        debug_log.routing_decision(
            session_id=session_id,
            current_phase=current_phase,
            detected_intent=detected_intent,
            destination=destination,
            reason=reason,
        )
    else:
        logger.info(
            "🔀 [SESSION %s] → %s (%s)",
            session_id,
            destination,
            reason,
        )


# Type aliases for routing destinations
MasterRoute = Literal[
    "moderation", "agent", "offer", "payment", "upsell", "escalation", "end"
    # crm_error removed - CRM orders integration disabled
]
ModerationRoute = Literal["intent", "escalation"]
IntentRoute = Literal["vision", "agent", "offer", "payment", "escalation"]
ValidationRoute = Literal["agent", "escalation", "end"]
AgentRoute = Literal["validation", "offer", "end"]
OfferRoute = Literal["payment", "validation", "end"]


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

    # Get thread_id for observability
    thread_id = metadata.get("thread_id", session_id)
    
    logger.info(
        " [SESSION %s] Master router: trace_id=%s phase=%s has_image=%s intent=%s msg='%s' thread_id=%s",
        session_id,
        trace_id,
        dialog_phase,
        has_image,
        detected_intent,
        user_message[:50] if user_message else "",
        thread_id,
    )

    # =========================================================================
    # SPECIAL CASES (highest priority)
    # =========================================================================
    # CRITICAL: Use unified photo purpose detection (SSOT)
    if has_image:
        from src.agents.langgraph.rules.photo_purpose import determine_photo_purpose
        from src.services.observability import track_metric
        
        photo_purpose, reason = determine_photo_purpose(state, user_message)
        
        # Set metadata for product addition context if needed
        if photo_purpose == "product_ident" and reason == "product_addition_intent_in_payment_phase":
            if "metadata" not in state:
                state["metadata"] = {}
            state["metadata"]["product_addition_context"] = True
            state["metadata"]["intent"] = "PRODUCT_ADDITION"
        
        # Route based on photo purpose
        if photo_purpose == "product_ident":
            track_metric(
                "image_routed_to_vision",
                1,
                {
                    "session_id": session_id,
                    "phase": dialog_phase,
                    "thread_id": thread_id,
                    "reason": reason,
                },
            )
            _route_debug(
                session_id=session_id,
                current_phase=dialog_phase,
                detected_intent=detected_intent,
                destination="moderation",
                reason=f"photo purpose: {photo_purpose} ({reason})",
            )
            return "moderation"
        elif photo_purpose == "transactional":
            track_metric(
                "image_routed_to_payment",
                1,
                {
                    "session_id": session_id,
                    "phase": dialog_phase,
                    "thread_id": thread_id,
                    "reason": reason,
                },
            )
            _route_debug(
                session_id=session_id,
                current_phase=dialog_phase,
                detected_intent=detected_intent,
                destination="payment",
                reason=f"photo purpose: {photo_purpose} ({reason})",
            )
            return "payment"
        else:  # context
            track_metric(
                "image_routed_to_agent",
                1,
                {
                    "session_id": session_id,
                    "phase": dialog_phase,
                    "thread_id": thread_id,
                    "reason": reason,
                },
            )
            _route_debug(
                session_id=session_id,
                current_phase=dialog_phase,
                detected_intent=detected_intent,
                destination="agent",
                reason=f"photo purpose: {photo_purpose} ({reason})",
            )
            return "agent"

    if detected_intent == "COMPLAINT":
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="escalation",
            reason="COMPLAINT detected in message",
        )
        return "escalation"

    # CRM ERROR HANDLING removed - CRM orders integration disabled
    # If CRM_ERROR_HANDLING phase is set, route to escalation instead
    if dialog_phase == "CRM_ERROR_HANDLING":
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="escalation",
            reason="CRM_ERROR_HANDLING_fallback_to_escalation",
        )
        return "escalation"

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
        confirmation_keywords = INTENT_PATTERNS.get("CONFIRMATION", [])
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
        # "crm_error": "crm_error",  # Removed - CRM orders integration disabled
        "end": "end",
    }


def route_after_moderation(state: dict[str, Any]) -> ModerationRoute:
    """
    Route after moderation check.

    - Blocked -> escalation
    - Allowed -> intent detection
    """
    # Перевіряємо moderation_result, НЕ should_escalate!
    # should_escalate може залишитись від попередньої ескалації
    moderation_result = state.get("moderation_result", {})
    if moderation_result.get("allowed") is False:
        logger.info("Routing to escalation: moderation blocked")
        return "escalation"
    return "intent"


def route_after_intent(state: dict[str, Any]) -> IntentRoute:
    """
    Route based on detected intent.

    This is the main routing decision point.
    """
    # Перевіряємо intent, НЕ should_escalate!
    detected_intent = state.get("detected_intent", "")
    if detected_intent == "COMPLAINT":
        return "escalation"

    intent = state.get("detected_intent", "DISCOVERY_OR_QUESTION")
    current_state = state.get("current_state", "")

    route = _resolve_intent_route(intent, current_state, state)
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", "?"))
    logger.info(
        "🚦 [SESSION %s] ROUTING: intent=%s, current_state=%s -> next=%s",
        session_id,
        intent,
        current_state,
        route,
    )
    return route


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
        # STATE_5: Always route to payment node for payment flow
        if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
            return "payment"

        # STATE_4: User confirmed offer ("беру") → payment node
        if current_state == State.STATE_4_OFFER.value:
            return "payment"

        # Has products but not yet in payment → offer
        if state.get("selected_products") or state.get("offered_products"):
            return "offer"

        return "agent"

    # Size/color with products -> offer
    if intent in ["SIZE_HELP", "COLOR_HELP"] and state.get("selected_products"):
        return "offer"

    # REQUEST_PHOTO - user wants to see product photos (no attachment)
    # Route to agent which will show photos from catalog
    if intent == "REQUEST_PHOTO":
        return "agent"  # Explicit routing (was implicit fallback)

    # PRODUCT_CATEGORY - user browsing by clothing type (костюм, сукня)
    # Route to agent for discovery/recommendations
    if intent == "PRODUCT_CATEGORY":
        return "agent"  # Explicit routing (was implicit fallback)

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


def route_after_agent(state: dict[str, Any]) -> AgentRoute:
    """
    Route after agent response.

    Turn-Based: Якщо agent встановив dialog_phase що потребує очікування,
    йдемо в END щоб повернути відповідь користувачу.
    """
    dialog_phase = state.get("dialog_phase", "INIT")

    # =========================================================================
    # Turn-Based: Phases that require waiting for user input → END
    # =========================================================================
    waiting_phases = {
        "DISCOVERY",  # Чекаємо зріст/тип речі
        "VISION_DONE",  # Чекаємо уточнення після фото
        "WAITING_FOR_SIZE",  # Чекаємо зріст
        "WAITING_FOR_COLOR",  # Чекаємо вибір кольору
        "OFFER_MADE",  # Чекаємо "Беру"
        "WAITING_FOR_DELIVERY_DATA",  # Чекаємо ПІБ, НП
        "WAITING_FOR_PAYMENT_METHOD",  # Чекаємо спосіб оплати
        "WAITING_FOR_PAYMENT_PROOF",  # Чекаємо скрін
        "UPSELL_OFFERED",  # Чекаємо відповідь на допродаж
        "COMPLETED",  # Діалог завершено
        "ESCALATED",  # Ескалація до менеджера - чекаємо відповіді від менеджера
    }

    if dialog_phase in waiting_phases:
        logger.info(
            "Agent → END (Turn-Based: waiting for user, phase=%s)",
            dialog_phase,
        )
        return "end"

    # =========================================================================
    # SIZE_COLOR_DONE → ready for offer
    # =========================================================================
    if dialog_phase == "SIZE_COLOR_DONE":
        logger.info("Agent → offer (SIZE_COLOR_DONE)")
        return "offer"

    # =========================================================================
    # Error → validation for retry
    # =========================================================================
    if state.get("last_error"):
        return "validation"

    # =========================================================================
    # Default → validate then end
    # =========================================================================
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


def route_after_vision(state: dict[str, Any]) -> Literal["offer", "agent", "validation", "end"]:
    """
    Route after vision processing.

    ВАЖЛИВО: Якщо vision впізнав товар і сформував відповідь з питанням про розмір,
    ми повертаємо END (віддаємо повідомлення користувачу) замість offer/agent.
    Offer буде після того як користувач відповість і ми зберемо розмір.
    """
    # Error -> validate
    if state.get("last_error"):
        return "validation"

    # Always end after vision to deliver vision-built messages to the user.
    # Next turn will continue based on dialog_phase (VISION_DONE / WAITING_FOR_SIZE / INIT).
    return "end"


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
    """Get route map for moderation node.

    Memory System: moderation → memory_context → intent
    """
    return {
        "intent": "memory_context",  # Changed: go through memory_context first
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
