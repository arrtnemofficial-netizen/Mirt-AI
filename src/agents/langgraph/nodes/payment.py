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

    logger.info(
        "[SESSION %s] Payment node entry: dialog_phase=%s, approval_type=%s",
        session_id,
        dialog_phase,
        approval_type,
    )

    # =========================================================================
    # ROUTING LOGIC - Determine which handler to call
    # =========================================================================

    # If we're in HITL mode and have a pending approval response
    if approval_type == "payment" and state.get("awaiting_human_approval"):
        # Human has responded to payment approval request
        return await handle_approval_response(state, session_id)

    # Determine handler based on dialog_phase
    if dialog_phase == "WAITING_FOR_PAYMENT_METHOD":
        # User is selecting payment method
        return await handle_payment_method_selection(state, runner, session_id)

    if dialog_phase in ("WAITING_FOR_DELIVERY_DATA", "WAITING_FOR_PAYMENT_PROOF"):
        # User is providing delivery data or payment proof
        return await handle_delivery_data(state, runner, session_id)

    # Default: Start checkout flow (initial entry to payment)
    return await prepare_payment_and_interrupt(state, runner, session_id)


# =============================================================================
# RE-EXPORTS FOR BACKWARD COMPATIBILITY (Tests patch these)
# =============================================================================
# These are re-exported so tests can patch at the payment.py level.
# New code should import directly from helpers.payment or the source modules.

from src.agents.pydantic.payment_agent import run_payment  # noqa: F401
from src.services.observability import log_agent_step, track_metric  # noqa: F401
from langgraph.types import interrupt  # noqa: F401

# Also re-export helpers for any existing imports
_ensure_prices_from_catalog = ensure_prices_from_catalog
_prepare_payment_and_interrupt = prepare_payment_and_interrupt
_handle_payment_method_selection = handle_payment_method_selection
_handle_delivery_data = handle_delivery_data
_handle_approval_response = handle_approval_response
_persist_order_and_queue_crm = persist_order_and_queue_crm
