from __future__ import annotations

from src.agents.langgraph.fsm.transition_reducer import compute_transition


def test_compute_transition_marks_has_deferred_intents() -> None:
    transition = compute_transition(
        state={"current_state": "STATE_1_DISCOVERY", "metadata": {}},
        intent="DISCOVERY_OR_QUESTION",
        deferred_intents=["PAYMENT_DELIVERY", "COLOR_HELP"],
    )

    assert transition.has_deferred_intents is True
