"""Consistency tests for routing + reducer decisions."""

from __future__ import annotations

import pytest

from src.agents.langgraph.edges import _resolve_intent_route
from src.agents.langgraph.fsm.transition_reducer import compute_transition
from src.agents.langgraph.nodes.handlers.transition_handler import finalize_transition
from src.agents.langgraph.nodes.intent import detect_intent_from_text
from src.agents.pydantic.models import MessageItem, ResponseMetadata, SupportResponse
from src.core.state_machine import State


def _state(state: State, message: str, *, dialog_phase: str = "WAITING_FOR_DELIVERY_DATA") -> dict:
    return {
        "session_id": "state5_consistency",
        "current_state": state.value,
        "dialog_phase": dialog_phase,
        "detected_intent": detect_intent_from_text(message, has_image=False, current_state=state.value),
        "messages": [{"role": "user", "content": message}],
        "selected_products": [{"name": "Тест", "price": 100, "size": "122-128"}],
        "metadata": {"session_id": "state5_consistency"},
    }


@pytest.mark.parametrize("state_enum", [s for s in State])
def test_photo_ident_route_always_goes_to_vision(state_enum: State) -> None:
    assert _resolve_intent_route("PHOTO_IDENT", state_enum.value, {}) == "vision"


def test_state5_short_ack_from_detected_intent_stays_in_payment_via_ssot() -> None:
    state = _state(State.STATE_5_PAYMENT_DELIVERY, "ок")
    decision = compute_transition(
        state=state,
        intent="THANKYOU_SMALLTALK",
        has_image=False,
        user_message="ок",
    )
    response = SupportResponse(
        event="simple_answer",
        messages=[MessageItem(type="text", content="ок")],
        products=[],
        metadata=ResponseMetadata(
            session_id="state5_consistency",
            current_state=State.STATE_5_PAYMENT_DELIVERY.value,
            intent="THANKYOU_SMALLTALK",
            escalation_level="NONE",
        ),
    )

    new_state, _, transition_meta = finalize_transition(state, response, "ок")

    assert new_state == State.STATE_5_PAYMENT_DELIVERY.value
    assert decision.next_state == State.STATE_5_PAYMENT_DELIVERY.value
    assert "strict_state5_short_ack_override" in decision.reason
    assert transition_meta["transition_source"] == "intent_node"
    assert transition_meta["payment_sub_phase"] == "REQUEST_DATA"


def test_state5_explicit_cancel_routes_to_end() -> None:
    state = _state(State.STATE_5_PAYMENT_DELIVERY, "відміна")

    response = SupportResponse(
        event="simple_answer",
        messages=[MessageItem(type="text", content="відміна")],
        products=[],
        metadata=ResponseMetadata(
            session_id="state5_consistency",
            current_state=State.STATE_5_PAYMENT_DELIVERY.value,
            intent="THANKYOU_SMALLTALK",
            escalation_level="NONE",
        ),
    )
    new_state, _, _ = finalize_transition(state, response, "відміна")

    decision = compute_transition(
        state=state,
        intent=state["detected_intent"],
        has_image=False,
        user_message="відміна",
    )

    assert new_state == State.STATE_7_END.value
    assert decision.next_state == State.STATE_7_END.value
    assert state["detected_intent"] == "THANKYOU_SMALLTALK"
