"""Consistency tests for routing + reducer decisions."""

from __future__ import annotations

import pytest

from src.agents.langgraph.edges import _resolve_intent_route
from src.agents.langgraph.fsm.transition_reducer import compute_transition
from src.agents.langgraph.nodes.handlers.transition_handler import finalize_transition
from src.agents.langgraph.nodes.intent import detect_intent_from_text
from src.agents.pydantic.models import MessageItem, ResponseMetadata, SupportResponse
from src.core.state_machine import Intent, State, map_state_to_router_node, resolve_next_state


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


def test_ambiguous_intent_routes_to_agent_disambiguation_branch() -> None:
    assert _resolve_intent_route("AMBIGUOUS", State.STATE_4_OFFER.value, {}) == "agent"


@pytest.mark.parametrize(
    ("current_state", "intent", "message", "has_image"),
    [
        (State.STATE_0_INIT, "DISCOVERY_OR_QUESTION", "покажи костюм", False),
        (State.STATE_4_OFFER, "PAYMENT_DELIVERY", "беру", False),
        (State.STATE_5_PAYMENT_DELIVERY, "THANKYOU_SMALLTALK", "відміна", False),
        (State.STATE_1_DISCOVERY, "COMPLAINT", "скарга", False),
        (State.STATE_3_SIZE_COLOR, "PHOTO_IDENT", "", True),
    ],
)
def test_next_state_ssot_is_identical_for_all_entry_points(
    current_state: State,
    intent: str,
    message: str,
    has_image: bool,
) -> None:
    state = {
        "session_id": "ssot-entrypoints",
        "current_state": current_state.value,
        "detected_intent": intent,
        "has_image": has_image,
        "messages": [{"role": "user", "content": message}],
        "selected_products": [{"name": "Тест", "price": 100}],
        "metadata": {"session_id": "ssot-entrypoints", "has_image": has_image},
    }

    ssot_state = resolve_next_state(current_state, Intent.from_string(intent)).value
    route = _resolve_intent_route(intent, current_state.value, {"has_image": has_image})
    route_state = resolve_next_state(current_state, Intent.from_string(intent)).value
    assert route == map_state_to_router_node(State.from_string(route_state))

    transition = compute_transition(
        state=state,
        intent=intent,
        has_image=has_image,
        user_message=message,
    )

    response = SupportResponse(
        event="simple_answer",
        messages=[MessageItem(type="text", content=message or "ok")],
        products=[],
        metadata=ResponseMetadata(
            session_id="ssot-entrypoints",
            current_state=current_state.value,
            intent=intent,
            escalation_level="NONE",
        ),
    )
    finalized_state, _, _ = finalize_transition(state, response, message)

    assert transition.next_state == ssot_state
    assert finalized_state == ssot_state
