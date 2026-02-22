"""Regression gate: route_after_intent must align with FSM transition decisions."""

from __future__ import annotations

import pytest

from src.agents.langgraph.fsm.transition_reducer import compute_transition
from src.agents.langgraph.routers.intent import route_after_intent
from src.core.state_machine import State


@pytest.mark.regression
@pytest.mark.parametrize(
    ("current_state", "intent", "has_image", "expected_route", "expected_next_state"),
    [
        (State.STATE_5_PAYMENT_DELIVERY.value, "PAYMENT_DELIVERY", False, "payment", State.STATE_5_PAYMENT_DELIVERY.value),
        (State.STATE_4_OFFER.value, "PAYMENT_DELIVERY", False, "payment", State.STATE_5_PAYMENT_DELIVERY.value),
        (State.STATE_4_OFFER.value, "PHOTO_IDENT", True, "vision", State.STATE_4_OFFER.value),
        (State.STATE_4_OFFER.value, "COMPLAINT", False, "escalation", State.STATE_6_ESCALATION.value),
    ],
)
def test_route_and_fsm_do_not_diverge(
    current_state: str,
    intent: str,
    has_image: bool,
    expected_route: str,
    expected_next_state: str,
) -> None:
    state = {
        "session_id": "route-fsm-regression",
        "current_state": current_state,
        "dialog_phase": "WAITING_FOR_DELIVERY_DATA",
        "detected_intent": intent,
        "messages": [{"role": "user", "content": "test"}],
        "selected_products": [{"name": "Тест", "price": 100, "size": "122-128"}],
        "offered_products": [{"name": "Тест", "price": 100, "size": "122-128"}],
        "metadata": {"session_id": "route-fsm-regression"},
        "has_image": has_image,
    }

    route = route_after_intent(state)
    decision = compute_transition(
        state=state,
        intent=intent,
        has_image=has_image,
        user_message="test",
    )

    assert route == expected_route
    assert decision.next_state == expected_next_state
