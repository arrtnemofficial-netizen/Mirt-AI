"""
Agent Business Logic.
====================
Core decision making rules:
- Dialog phase transitions (State Machine)
- Intent instructions
- Upsell triggers
- Payment flow overrides
"""
from __future__ import annotations

import logging
from typing import Any

from src.agents.langgraph.state_prompts import (
    determine_next_dialog_phase,
    get_payment_sub_phase,
)
from src.core.state_machine import State, expected_state_for_phase
from src.services.core.observability import track_metric

logger = logging.getLogger(__name__)

UPSELL_STATE = State.STATE_6_UPSELL.value


def determine_phase(
    current_state: str,
    event: str,
    selected_products: list,
    metadata: Any,
    state: dict[str, Any] | None = None,
) -> str:
    """
    Determine dialog_phase from LLM response for Turn-Based routing.
    Wrapper around state_prompts logic with added safe-guards.
    """
    # Escalation always ends dialog
    if event == "escalation":
        return "COMPLETED"

    has_products = bool(selected_products)

    # Check for size/color
    has_size = False
    has_color = False
    if selected_products:
        first_product = selected_products[0]
        has_size = bool(first_product.get("size"))
        has_color = bool(first_product.get("color"))

        # FALLBACK: Color may be embedded in name
        if not has_color:
            product_name = first_product.get("name", "")
            if "(" in product_name and ")" in product_name:
                has_color = True

    # Get intent
    intent = ""
    if hasattr(metadata, "intent"):
        intent = metadata.intent
    elif isinstance(metadata, dict):
        intent = metadata.get("intent", "")

    # Check confirmation
    user_confirmed = event in ("simple_answer",) and intent == "PAYMENT_DELIVERY"

    # Payment sub-phase
    payment_sub_phase = None
    if current_state == State.STATE_5_PAYMENT_DELIVERY.value and state:
        payment_sub_phase = get_payment_sub_phase(state)

    return determine_next_dialog_phase(
        current_state=current_state,
        intent=intent,
        has_products=has_products,
        has_size=has_size,
        has_color=has_color,
        user_confirmed=user_confirmed,
        payment_sub_phase=payment_sub_phase,
    )


def validate_fsm_transition(
    dialog_phase: str,
    new_state_str: str,
    session_id: str,
) -> str:
    """Validate and correct state transition based on FSM rules."""
    expected_state = expected_state_for_phase(dialog_phase)
    
    if expected_state and new_state_str != expected_state.value:
        logger.warning(
            "FSM guard override: phase=%s expected_state=%s got=%s (session=%s)",
            dialog_phase,
            expected_state.value,
            new_state_str,
            session_id,
        )
        track_metric(
            "fsm_guard_override",
            1,
            {
                "phase": dialog_phase,
                "expected_state": expected_state.value,
                "actual_state": new_state_str,
            },
        )
        return expected_state.value
        
    return new_state_str


def should_trigger_upsell(
    selected_products: list,
    *,
    current_state: str,
    next_state: str,
    upsell_flow_active: bool,
) -> bool:
    """Check if upsell logic should be triggered (appending items)."""
    if not selected_products:
        return False
    if upsell_flow_active:
        return True
    return current_state == UPSELL_STATE or next_state == UPSELL_STATE


def check_payment_override(
    current_state: str,
    dialog_phase: str,
    intent: str,
    llm_new_state: str,
) -> tuple[str, bool]:
    """
    Check if we need to force transition to PAYMENT_DELIVERY.
    Returns: (final_state, changed)
    """
    if current_state == State.STATE_4_OFFER.value and dialog_phase == "OFFER_MADE":
        if intent == "PAYMENT_DELIVERY" and llm_new_state == State.STATE_4_OFFER.value:
            return State.STATE_5_PAYMENT_DELIVERY.value, True

    return llm_new_state, False
