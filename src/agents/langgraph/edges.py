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

# Import for intent detection
from .state_prompts import detect_simple_intent


logger = logging.getLogger(__name__)


# Type aliases for routing destinations
MasterRoute = Literal["moderation", "agent", "offer", "payment", "upsell", "escalation", "end"]
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


def _extract_user_message(state: dict[str, Any]) -> str:
    """Extract last user message text from state."""
    messages = state.get("messages", [])
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            return m.get("content", "")
        elif hasattr(m, "type") and m.type == "human":
            return m.content if hasattr(m, "content") else ""
    return ""


def master_router(state: dict[str, Any]) -> MasterRoute:
    """
    Master router - checks dialog_phase to determine where to continue.

    QUALITY IMPLEMENTATION:
    - Враховує dialog_phase
    - Аналізує intent з повідомлення користувача
    - Правильно маршрутизує на основі контексту
    """
    dialog_phase = state.get("dialog_phase", "INIT")
    session_id = state.get("session_id", "?")
    has_image = state.get("has_image", False)

    # QUALITY: Отримуємо останнє повідомлення для аналізу intent
    user_message = _extract_user_message(state)
    detected_intent = detect_simple_intent(user_message) if user_message else None

    logger.info(
        "🔀 [SESSION %s] Master router: phase=%s, has_image=%s, intent=%s, msg='%s'",
        session_id,
        dialog_phase,
        has_image,
        detected_intent,
        user_message[:50] if user_message else "",
    )

    # =========================================================================
    # RULE 1: NEW IMAGE always goes through full pipeline
    # =========================================================================
    if has_image:
        logger.info("🔀 [SESSION %s] → moderation (new image)", session_id)
        return "moderation"

    # =========================================================================
    # RULE 2: COMPLAINT intent overrides everything
    # =========================================================================
    if detected_intent == "COMPLAINT":
        logger.info("🔀 [SESSION %s] → escalation (COMPLAINT detected)", session_id)
        return "escalation"

    # =========================================================================
    # RULE 3: Route based on dialog_phase + intent
    # =========================================================================

    # STATE_1: Discovery - збір контексту (зріст, тип речі)
    if dialog_phase == "DISCOVERY":
        logger.info("🔀 [SESSION %s] → agent (DISCOVERY)", session_id)
        return "agent"

    # STATE_2→3: Vision done - потрібно уточнення
    if dialog_phase == "VISION_DONE":
        logger.info("🔀 [SESSION %s] → agent (VISION_DONE)", session_id)
        return "agent"

    # STATE_3: Waiting for size
    if dialog_phase == "WAITING_FOR_SIZE":
        # Якщо юзер каже "беру" замість розміру - йдемо в payment
        if detected_intent == "PAYMENT_DELIVERY":
            logger.info("🔀 [SESSION %s] → payment (WAITING_FOR_SIZE but got 'беру')", session_id)
            return "payment"
        logger.info("🔀 [SESSION %s] → agent (WAITING_FOR_SIZE)", session_id)
        return "agent"

    # STATE_3: Waiting for color
    if dialog_phase == "WAITING_FOR_COLOR":
        if detected_intent == "PAYMENT_DELIVERY":
            logger.info("🔀 [SESSION %s] → payment (WAITING_FOR_COLOR but got 'беру')", session_id)
            return "payment"
        logger.info("🔀 [SESSION %s] → agent (WAITING_FOR_COLOR)", session_id)
        return "agent"

    # STATE_3→4: Size and color ready
    if dialog_phase == "SIZE_COLOR_DONE":
        logger.info("🔀 [SESSION %s] → offer (SIZE_COLOR_DONE)", session_id)
        return "offer"

    # STATE_4: Offer made - чекаємо "Беру"
    if dialog_phase == "OFFER_MADE":
        # QUALITY: Перевіряємо чи юзер каже "беру"
        if detected_intent == "PAYMENT_DELIVERY":
            logger.info("🔀 [SESSION %s] → payment (OFFER_MADE + 'беру')", session_id)
            return "payment"
        # Інакше - юзер питає щось інше
        logger.info("🔀 [SESSION %s] → agent (OFFER_MADE, clarifying)", session_id)
        return "agent"

    # STATE_5: Collecting delivery data
    if dialog_phase == "WAITING_FOR_DELIVERY_DATA":
        logger.info("🔀 [SESSION %s] → payment (WAITING_FOR_DELIVERY_DATA)", session_id)
        return "payment"

    # STATE_5: Waiting for payment method
    if dialog_phase == "WAITING_FOR_PAYMENT_METHOD":
        logger.info("🔀 [SESSION %s] → payment (WAITING_FOR_PAYMENT_METHOD)", session_id)
        return "payment"

    # STATE_5: Waiting for payment proof
    if dialog_phase == "WAITING_FOR_PAYMENT_PROOF":
        logger.info("🔀 [SESSION %s] → payment (WAITING_FOR_PAYMENT_PROOF)", session_id)
        return "payment"

    # STATE_6: Upsell offered
    if dialog_phase == "UPSELL_OFFERED":
        logger.info("🔀 [SESSION %s] → upsell (UPSELL_OFFERED)", session_id)
        return "upsell"

    # STATE_7: Completed - but user wrote again
    if dialog_phase == "COMPLETED":
        # QUALITY: Якщо юзер пише після COMPLETED - новий діалог
        if detected_intent == "THANKYOU_SMALLTALK":
            logger.info("🔀 [SESSION %s] → end (COMPLETED + thanks)", session_id)
            return "end"
        logger.info("🔀 [SESSION %s] → moderation (COMPLETED but new query)", session_id)
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
        "end": "end",
    }


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
        payment_states = (State.STATE_4_OFFER.value, State.STATE_5_PAYMENT_DELIVERY.value)
        if current_state in payment_states:
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
        "DISCOVERY",                   # Чекаємо зріст/тип речі
        "VISION_DONE",                 # Чекаємо уточнення після фото
        "WAITING_FOR_SIZE",            # Чекаємо зріст
        "WAITING_FOR_COLOR",           # Чекаємо вибір кольору
        "OFFER_MADE",                  # Чекаємо "Беру"
        "WAITING_FOR_DELIVERY_DATA",   # Чекаємо ПІБ, НП
        "WAITING_FOR_PAYMENT_METHOD",  # Чекаємо спосіб оплати
        "WAITING_FOR_PAYMENT_PROOF",   # Чекаємо скрін
        "UPSELL_OFFERED",              # Чекаємо відповідь на допродаж
        "COMPLETED",                   # Діалог завершено
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
    ми повертаємо END (віддаємо повідомлення користувачу) замість offer.
    Offer буде після того як користувач обере розмір.
    """
    # Found products -> END (return multi-bubble response to user)
    # Vision вже питає про розмір, offer буде пізніше
    if state.get("selected_products"):
        return "end"

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
