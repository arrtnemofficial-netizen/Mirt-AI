"""Regression tests for policy-vs-router responsibility split."""

from __future__ import annotations

from src.agents.langgraph.intent.policy import select_intents
from src.agents.langgraph.routers.intent import route_after_intent
from src.core.state_machine import State


def test_policy_selects_payment_over_photo_ident_for_mixed_turn() -> None:
    selection = select_intents(["PHOTO_IDENT", "PAYMENT_DELIVERY"])
    assert selection.primary_intent == "PAYMENT_DELIVERY"



def test_router_does_not_override_photo_ident_without_image_signal() -> None:
    route = route_after_intent(
        {
            "session_id": "policy-router-contract",
            "current_state": State.STATE_1_DISCOVERY.value,
            "detected_intent": "PHOTO_IDENT",
            "has_image": False,
            "messages": [{"role": "user", "content": "фото"}],
            "metadata": {},
        }
    )

    assert route == "agent"
