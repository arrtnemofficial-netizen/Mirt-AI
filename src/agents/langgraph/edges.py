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
    "moderation", "agent", "offer", "payment", "upsell", "escalation", "end", "crm_error"
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
    # CRITICAL: Vision should ONLY run for FIRST photo in session (INIT/DISCOVERY)
    # All subsequent photos must be handled in current phase context to prevent restart
    if has_image:
        # CRITICAL: Check for EXPLICIT "new product" trigger FIRST
        # If user explicitly says "new product" + photo, ALWAYS route to vision (regardless of phase)
        if user_message:
            from src.agents.langgraph.nodes.helpers.policy_snippets import detect_explicit_new_product
            
            if detect_explicit_new_product(user_message, state):
                from src.services.observability import track_metric
                track_metric(
                    "image_routed_to_vision",
                    1,
                    {
                        "session_id": session_id,
                        "phase": dialog_phase,
                        "thread_id": thread_id,
                        "reason": "explicit_new_product_trigger",
                    },
                )
                _route_debug(
                    session_id=session_id,
                    current_phase=dialog_phase,
                    detected_intent=detected_intent,
                    destination="moderation",
                    reason="explicit 'new product' trigger detected, routing to vision",
                )
                return "moderation"
        
        # Feature flag: allow disabling phase-aware routing for rollback
        phase_aware_enabled = getattr(settings, "PHASE_AWARE_IMAGE_ROUTING", True)
        
        # Check if this is first photo in session
        vision_greeted = bool(metadata.get("vision_greeted", False))
        
        # Phases where vision is allowed (first photo scenarios)
        vision_allowed_phases = {"INIT", "DISCOVERY"}
        
        # Transactional phases where images should be interpreted as payment proof
        transactional_phases = {
            "WAITING_FOR_PAYMENT_PROOF",
            "WAITING_FOR_PAYMENT_METHOD",
            "WAITING_FOR_DELIVERY_DATA",
        }
        
        if phase_aware_enabled:
            # CRITICAL: If already greeted, NEVER route to vision (prevents restart)
            if vision_greeted and dialog_phase not in vision_allowed_phases:
                # Photo in ongoing conversation - handle in current context
                from src.services.observability import track_metric
                
                if dialog_phase in transactional_phases:
                    # Payment/delivery phases: route to payment
                    track_metric(
                        "image_routed_to_payment",
                        1,
                        {
                            "session_id": session_id,
                            "phase": dialog_phase,
                            "thread_id": thread_id,
                            "reason": "ongoing_conversation_payment",
                        },
                    )
                    _route_debug(
                        session_id=session_id,
                        current_phase=dialog_phase,
                        detected_intent=detected_intent,
                        destination="payment",
                        reason=f"ongoing conversation: image in {dialog_phase} (already greeted)",
                    )
                    return "payment"
                else:
                    # Other phases: route to agent to handle in context
                    track_metric(
                        "image_routed_to_agent",
                        1,
                        {
                            "session_id": session_id,
                            "phase": dialog_phase,
                            "thread_id": thread_id,
                            "reason": "ongoing_conversation",
                        },
                    )
                    _route_debug(
                        session_id=session_id,
                        current_phase=dialog_phase,
                        detected_intent=detected_intent,
                        destination="agent",
                        reason=f"ongoing conversation: image in {dialog_phase} (already greeted, handle in context)",
                    )
                    return "agent"
            
            # Transactional phases: always route to payment (even if not greeted yet)
            if dialog_phase in transactional_phases:
                from src.services.observability import track_metric
                track_metric(
                    "image_routed_to_payment",
                    1,
                    {
                        "session_id": session_id,
                        "phase": dialog_phase,
                        "thread_id": thread_id,
                        "reason": "transactional_phase",
                    },
                )
                _route_debug(
                    session_id=session_id,
                    current_phase=dialog_phase,
                    detected_intent=detected_intent,
                    destination="payment",
                    reason=f"phase-aware routing: image in {dialog_phase}",
                )
                return "payment"
            
            # CRITICAL: If phase is NOT INIT/DISCOVERY and NOT transactional, 
            # route to agent (NOT vision) to prevent restart, even if vision_greeted=False
            # This handles cases like WAITING_FOR_SIZE, WAITING_FOR_COLOR, OFFER_MADE, etc.
            if dialog_phase not in vision_allowed_phases:
                from src.services.observability import track_metric
                track_metric(
                    "image_routed_to_agent",
                    1,
                    {
                        "session_id": session_id,
                        "phase": dialog_phase,
                        "thread_id": thread_id,
                        "reason": "mid_conversation_phase",
                    },
                )
                _route_debug(
                    session_id=session_id,
                    current_phase=dialog_phase,
                    detected_intent=detected_intent,
                    destination="agent",
                    reason=f"photo in {dialog_phase} (not INIT/DISCOVERY, handle in context)",
                )
                return "agent"
        
        # First photo in session (INIT/DISCOVERY) or phase-aware disabled: route to vision
        from src.services.observability import track_metric
        track_metric(
            "image_routed_to_vision",
            1,
            {
                "session_id": session_id,
                "phase": dialog_phase,
                "thread_id": thread_id,
                "reason": "first_photo" if not vision_greeted else "phase_aware_disabled",
            },
        )
        _route_debug(
            session_id=session_id,
            current_phase=dialog_phase,
            detected_intent=detected_intent,
            destination="moderation",
            reason="first photo in session or phase-aware disabled",
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
        "crm_error": "crm_error",
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
