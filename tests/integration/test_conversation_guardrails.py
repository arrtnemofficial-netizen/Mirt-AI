import pytest
import copy
from src.services.conversation.guardrails import apply_transition_guardrails


def _stagnant_state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "messages": [],
        "metadata": {
            "session_id": session_id,
            "FORCE_STAGNANT": True
        },
        "current_state": "STATE_5_PAYMENT_DELIVERY",
        "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
    }


@pytest.mark.asyncio
async def test_apply_transition_guardrails_soft_recovery():
    session_id = "sess_guard_direct_10"
    before_state = _stagnant_state(session_id)
    
    current_state = copy.deepcopy(before_state)
    for i in range(10):
        # The 'before_state' for turn N is the 'after_state' of turn N-1
        b_state = copy.deepcopy(current_state)
        # Force stagnant fingerprint if it recovered
        if b_state.get("dialog_phase") == "INIT":
             b_state["current_state"] = "STATE_5_PAYMENT_DELIVERY"
             b_state["dialog_phase"] = "WAITING_FOR_PAYMENT_PROOF"
        
        incoming_state = copy.deepcopy(b_state)
        current_state = apply_transition_guardrails(
            session_id=session_id,
            before_state=b_state,
            after_state=incoming_state,
            user_text="ок"
        )
    
    assert current_state.get("last_error") == "loop_guard_soft_recovery"
    assert current_state.get("current_state") == "STATE_0_INIT"
    assert current_state.get("dialog_phase") == "INIT"


@pytest.mark.asyncio
async def test_apply_transition_guardrails_escalation():
    session_id = "sess_guard_direct_20"
    before_state = _stagnant_state(session_id)
    
    current_state = copy.deepcopy(before_state)
    for i in range(20):
        b_state = copy.deepcopy(current_state)
        # Always force stagnation to reach turn 20
        b_state["current_state"] = "STATE_5_PAYMENT_DELIVERY"
        b_state["dialog_phase"] = "WAITING_FOR_PAYMENT_PROOF"
        b_state["metadata"]["FORCE_STAGNANT"] = True
        
        incoming_state = copy.deepcopy(b_state)
        current_state = apply_transition_guardrails(
            session_id=session_id,
            before_state=b_state,
            after_state=incoming_state,
            user_text="ок"
        )
    
    # After 20 turns, should be escalation
    assert current_state.get("last_error") == "loop_guard_escalation"
    assert current_state.get("current_state") == "STATE_8_COMPLAINT"
    assert current_state.get("dialog_phase") == "COMPLAINT"
    assert current_state.get("should_escalate") is True
