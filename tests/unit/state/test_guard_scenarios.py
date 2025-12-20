"""
E2E: Guard scenarios for dialog phase and illegal state jumps.

These tests target production regressions:
- "repeat height": phase says size is done but state regresses to size collection.
- "state jump": illegal transition to payment from discovery.
"""

from src.core.state_machine import State
from src.services.conversation import _apply_transition_guardrails


def _base_state() -> dict:
    return {
        "session_id": "sess_guard_e2e",
        "messages": [],
        "metadata": {"session_id": "sess_guard_e2e"},
        "selected_products": [],
        "offered_products": [],
    }


def test_repeat_height_phase_forces_offer_state():
    """
    If dialog_phase indicates size/color done, state must be STATE_4_OFFER.
    This prevents re-asking for height after it was already provided.
    """
    before_state = {
        **_base_state(),
        "current_state": State.STATE_3_SIZE_COLOR.value,
        "dialog_phase": "WAITING_FOR_SIZE",
        "detected_intent": "SIZE_HELP",
    }
    after_state = {
        **_base_state(),
        "current_state": State.STATE_3_SIZE_COLOR.value,  # bad regression
        "dialog_phase": "SIZE_COLOR_DONE",
        "detected_intent": "SIZE_HELP",
    }

    result = _apply_transition_guardrails(
        session_id="sess_guard_e2e",
        before_state=before_state,
        after_state=after_state,
        user_text="Height is 124",
    )

    assert result["current_state"] == State.STATE_4_OFFER.value


def test_illegal_state_jump_is_blocked():
    """
    Illegal jump from discovery to payment should be blocked by guardrails.
    """
    before_state = {
        **_base_state(),
        "current_state": State.STATE_1_DISCOVERY.value,
        "dialog_phase": "DISCOVERY",
        "detected_intent": "DISCOVERY_OR_QUESTION",
    }
    after_state = {
        **_base_state(),
        "current_state": State.STATE_5_PAYMENT_DELIVERY.value,  # illegal jump
        "dialog_phase": "DISCOVERY",
        "detected_intent": "DISCOVERY_OR_QUESTION",
    }

    result = _apply_transition_guardrails(
        session_id="sess_guard_e2e",
        before_state=before_state,
        after_state=after_state,
        user_text="I want to see options",
    )

    assert result["current_state"] == State.STATE_1_DISCOVERY.value
