"""
Payment Node - Human-in-the-loop for money.
============================================
CRITICAL NODE. This is where money changes hands.
MUST have human approval before processing.

QUALITY IMPLEMENTATION:
- Sub-phases: REQUEST_DATA → CONFIRM_DATA → SHOW_PAYMENT → THANK_YOU
- Детальні промпти для кожного кроку
- Правильна логіка переходів

MODULAR ARCHITECTURE:
This file contains ONLY the main router (payment_node).
All handlers are extracted to helpers/payment/ for maintainability:
- checkout.py: prepare_payment_and_interrupt
- method_selection.py: handle_payment_method_selection
- delivery.py: handle_delivery_data
- crm.py: persist_order_and_queue_crm
- approval.py: handle_approval_response
- utils.py: ensure_prices_from_catalog
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langgraph.types import Command

from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.agents.langgraph.nodes.helpers.vision.snippet_loader import get_snippet_by_header

# Import extracted handlers from helpers
from .helpers.payment import (
    ensure_prices_from_catalog,
    prepare_payment_and_interrupt,
    handle_payment_method_selection,
    handle_delivery_data,
    handle_approval_response,
    persist_order_and_queue_crm,
)


if TYPE_CHECKING:
    from collections.abc import Callable


logger = logging.getLogger(__name__)


# =============================================================================
# MAIN ROUTER
# =============================================================================

async def payment_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> Command:
    """
    Handle payment with MANDATORY human approval.

    This node uses LangGraph's interrupt() for human-in-the-loop.
    The graph STOPS here and waits for explicit approval.

    Flow:
        1. Collect delivery data (ПІБ, телефон, НП)
        2. Show requisites
        3. Wait for payment proof
        4. Upsell or complete
    """
    session_id = state.get("session_id", "unknown")
    trace_id = state.get("trace_id", "")
    dialog_phase = state.get("dialog_phase", "")
    approval_type = state.get("approval_type", "")

    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_entry(
            session_id=session_id,
            node_name="payment",
            state_keys=list(state.keys()),
            trace_id=trace_id,
        )

    # =========================================================================
    # SSOT: USE TRANSITION REDUCER FOR PAYMENT SUB-PHASE
    # =========================================================================
    # Використовуємо SSOT reducer для визначення payment_sub_phase
    # (get_payment_sub_phase все ще використовується всередині reducer)
    from src.agents.langgraph.fsm.transition_reducer import compute_transition
    from src.agents.langgraph.nodes.utils import extract_user_message
    
    user_message = extract_user_message(state.get("messages", []))
    detected_intent = state.get("detected_intent", "PAYMENT_DELIVERY")
    has_image = state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
    
    # Викликаємо SSOT reducer
    transition = compute_transition(
        state=state,
        intent=detected_intent,
        has_image=has_image,
        user_message=user_message,
    )
    
    payment_sub_phase = transition.payment_sub_phase or "REQUEST_DATA"
    computed_dialog_phase = transition.dialog_phase
    
    # SSOT: Використовуємо computed_dialog_phase (не зберіганий dialog_phase)
    # Але якщо dialog_phase вже встановлений і відрізняється - логуємо попередження
    if dialog_phase and dialog_phase != computed_dialog_phase:
        logger.warning(
            "[SESSION %s] ⚠️ Dialog phase mismatch: stored=%s, computed=%s. Using computed (SSOT).",
            session_id,
            dialog_phase,
            computed_dialog_phase,
        )
    
    logger.info(
        "[SESSION %s] Payment node entry: stored_dialog_phase=%s, computed_dialog_phase=%s, payment_sub_phase=%s, approval_type=%s",
        session_id,
        dialog_phase,
        computed_dialog_phase,
        payment_sub_phase,
        approval_type,
    )

    # =========================================================================
    # ROUTING LOGIC - Determine which handler to call based on sub-phase
    # =========================================================================

    # If we're in HITL mode and have a pending approval response
    if approval_type == "payment" and state.get("awaiting_human_approval"):
        # Human has responded to payment approval request
        return await handle_approval_response(state, session_id)

    # =========================================================================
    # SSOT ROUTING: Використовуємо payment_sub_phase (джерело правди)
    # =========================================================================
    # Routing на основі payment_sub_phase (не dialog_phase, який може бути застарілим)
    
    # REQUEST_DATA → prepare_payment_and_interrupt (використовує snippet)
    if payment_sub_phase == "REQUEST_DATA":
        logger.info("[SESSION %s] Routing to prepare_payment_and_interrupt (REQUEST_DATA)", session_id)
        return await prepare_payment_and_interrupt(state, runner, session_id)
    
    # CONFIRM_DATA → handle_payment_method_selection
    if payment_sub_phase == "CONFIRM_DATA":
        logger.info("[SESSION %s] Routing to handle_payment_method_selection (CONFIRM_DATA)", session_id)
        return await handle_payment_method_selection(state, runner, session_id)
    
    # SHOW_PAYMENT, THANK_YOU → handle_delivery_data
    if payment_sub_phase in ("SHOW_PAYMENT", "THANK_YOU"):
        logger.info("[SESSION %s] Routing to handle_delivery_data (sub_phase=%s)", session_id, payment_sub_phase)
        # КРИТИЧНО: Передаем payment_sub_phase из transition (SSOT) в state для использования в handle_delivery_data
        # Это избегает повторного вызова get_payment_sub_phase
        state_with_sub_phase = {**state, "_temp_context": {"payment_sub_phase": payment_sub_phase}}
        return await handle_delivery_data(state_with_sub_phase, runner, session_id)

    # Fallback: якщо payment_sub_phase не визначено, використовуємо computed_dialog_phase
    logger.warning(
        "[SESSION %s] Payment sub-phase not recognized: %s, using computed_dialog_phase=%s for routing",
        session_id,
        payment_sub_phase,
        computed_dialog_phase,
    )
    
    if computed_dialog_phase == "WAITING_FOR_PAYMENT_METHOD":
        return await handle_payment_method_selection(state, runner, session_id)
    elif computed_dialog_phase in ("WAITING_FOR_DELIVERY_DATA", "WAITING_FOR_PAYMENT_PROOF"):
        return await handle_delivery_data(state, runner, session_id)
    else:
        # Default: Start checkout flow
        logger.info("[SESSION %s] Default routing to prepare_payment_and_interrupt", session_id)
        return await prepare_payment_and_interrupt(state, runner, session_id)


