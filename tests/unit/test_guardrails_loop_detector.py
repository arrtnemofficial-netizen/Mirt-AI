from unittest.mock import patch

from src.services.guardrails.loop_detector import apply_loop_protection


def _state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "metadata": {"_guard": {"count": 19}},
        "current_state": "STATE_5_PAYMENT_DELIVERY",
        "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
        "detected_intent": "PAYMENT_PROOF",
        "selected_products": [],
        "offered_products": [],
    }


def test_loop_guard_escalation_response_fallback_when_human_response_errors():
    before_state = _state("sess_loop_fallback")
    after_state = _state("sess_loop_fallback")

    with patch(
        "src.core.human_responses.get_human_response",
        side_effect=ValueError("template error"),
    ):
        result = apply_loop_protection(
            session_id="sess_loop_fallback",
            before_state=before_state,
            after_state=after_state,
            user_text="ok",
        )

    assert result["last_error"] == "loop_guard_escalation"
    assert result["current_state"] == "STATE_8_COMPLAINT"
    assert result["dialog_phase"] == "COMPLAINT"
    assert result["should_escalate"] is True
    assert result["agent_response"]["event"] == "escalation"
    assert result["agent_response"]["messages"][0]["content"] == (
        "Передаю ваш запит менеджеру. Очікуйте, будь ласка."
    )
