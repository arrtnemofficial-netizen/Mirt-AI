import logging

from src.agents.langgraph.edges import master_router
from src.core.state_machine import State


def _state(
    *,
    current_state: State,
    user_message: str,
    dialog_phase: str,
    metadata: dict | None = None,
) -> dict:
    return {
        "session_id": "test_master_policy",
        "current_state": current_state.value,
        "dialog_phase": dialog_phase,
        "messages": [{"role": "user", "content": user_message}],
        "metadata": metadata or {},
        "has_image": False,
    }


def test_offer_question_routes_to_agent_by_intent(monkeypatch, caplog):
    monkeypatch.setattr("src.agents.langgraph.routers.master.settings.DEBUG_TRACE_LOGS", False)
    caplog.set_level(logging.INFO, logger="src.agents.langgraph.routers.master")

    route = master_router(
        _state(
            current_state=State.STATE_4_OFFER,
            user_message="А яка тканина і чи є інший колір?",
            dialog_phase="OFFER_MADE",
        )
    )

    assert route == "agent"
    assert "route_reason=intent" in caplog.text


def test_offer_confirmation_routes_to_payment_by_intent(monkeypatch, caplog):
    monkeypatch.setattr("src.agents.langgraph.routers.master.settings.DEBUG_TRACE_LOGS", False)
    caplog.set_level(logging.INFO, logger="src.agents.langgraph.routers.master")

    route = master_router(
        _state(
            current_state=State.STATE_4_OFFER,
            user_message="Так, беру, оформлюємо",
            dialog_phase="OFFER_MADE",
        )
    )

    assert route == "payment"
    assert "route_reason=intent" in caplog.text


def test_offer_phase_policy_has_priority_over_intent(monkeypatch, caplog):
    monkeypatch.setattr("src.agents.langgraph.routers.master.settings.DEBUG_TRACE_LOGS", False)
    caplog.set_level(logging.INFO, logger="src.agents.langgraph.routers.master")

    route = master_router(
        _state(
            current_state=State.STATE_4_OFFER,
            user_message="Яка ціна?",
            dialog_phase="WAITING_FOR_DELIVERY_DATA",
        )
    )

    assert route == "payment"
    assert "route_reason=phase_policy" in caplog.text


def test_payment_phase_policy_has_priority_over_intent(monkeypatch, caplog):
    monkeypatch.setattr("src.agents.langgraph.routers.master.settings.DEBUG_TRACE_LOGS", False)
    caplog.set_level(logging.INFO, logger="src.agents.langgraph.routers.master")

    route = master_router(
        _state(
            current_state=State.STATE_5_PAYMENT_DELIVERY,
            user_message="Я вже оплатив",
            dialog_phase="WAITING_FOR_DELIVERY_DATA",
            metadata={"payment_request_data_sent": True},
        )
    )

    assert route == "agent"
    assert "route_reason=phase_policy" in caplog.text
