"""
STATE_5 scenario regressions.

Covers payment-flow guardrails required for deterministic behavior:
- short acknowledgements without proof keep payment flow
- proof image completes payment flow
- product-addition photo does not get treated as payment proof
- off-topic questions in payment state do not force END
- explicit cancel can exit payment flow
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langgraph.types import Command

from src.agents.langgraph.fsm.transition_reducer import compute_transition
from src.agents.langgraph.nodes.handlers.transition_handler import finalize_transition
from src.agents.langgraph.nodes.intent import detect_intent_from_text
from src.agents.langgraph.routers.intent import route_after_intent
from src.agents.pydantic.models import MessageItem, ResponseMetadata, SupportResponse
from src.core.state_machine import State


def _base_state() -> dict[str, object]:
    return {
        "session_id": "state5_scenario",
        "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
        "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
        "selected_products": [{"name": "Тест", "price": 100}],
        "metadata": {"session_id": "state5_scenario"},
        "messages": [{"role": "user", "content": ""}],
        "step_number": 1,
    }


def test_state5_short_ack_without_proof_stays_in_payment():
    state = _base_state()

    transition = compute_transition(
        state=state,
        intent="THANKYOU_SMALLTALK",
        has_image=False,
        user_message="ок",
    )

    assert transition.next_state == State.STATE_5_PAYMENT_DELIVERY.value
    assert "strict_state5_short_ack_override" in transition.reason


def test_state5_explicit_cancel_can_end_flow():
    state = _base_state()
    intent = detect_intent_from_text(
        "скасувати",
        has_image=False,
        current_state=State.STATE_5_PAYMENT_DELIVERY.value,
    )
    assert intent == "THANKYOU_SMALLTALK"

    transition = compute_transition(
        state=state,
        intent=intent,
        has_image=False,
        user_message="скасувати",
    )

    assert transition.next_state == State.STATE_7_END.value


@pytest.mark.asyncio
async def test_state5_proof_image_completes_order():
    from src.agents.langgraph.nodes.helpers.payment.delivery import handle_delivery_data

    state = _base_state()
    state["has_image"] = True

    with patch(
        "src.agents.langgraph.nodes.helpers.payment.delivery.ensure_prices_from_catalog",
        new=AsyncMock(return_value=state["selected_products"]),
    ), patch(
        "src.agents.langgraph.rules.product_addition.detect_product_addition_intent",
        return_value=False,
    ), patch(
        "src.agents.langgraph.rules.payment_proof.detect_payment_proof",
        return_value=True,
    ), patch(
        "src.agents.langgraph.nodes.helpers.payment.delivery.persist_order_and_queue_crm",
        new=AsyncMock(return_value={"id": 42}),
    ), patch(
        "src.services.notifications.NotificationService.send_escalation_alert",
        new=AsyncMock(return_value=None),
    ), patch(
        "src.agents.langgraph.nodes.helpers.payment.delivery._check_upsell_opportunity",
        return_value=None,
    ), patch(
        "src.agents.langgraph.nodes.helpers.vision.snippet_loader.get_snippet_by_header",
        return_value=["ok"],
    ):
        result = await handle_delivery_data(state=state, runner=None, session_id="state5_scenario")

    assert result.goto == "end"
    assert result.update["current_state"] == State.STATE_7_END.value
    assert result.update["metadata"]["payment_proof_received"] is True


@pytest.mark.asyncio
async def test_state5_product_addition_photo_delegates_not_proof():
    from src.agents.langgraph.nodes.helpers.payment.delivery import handle_delivery_data

    state = _base_state()
    state["has_image"] = True
    state["messages"] = [{"role": "user", "content": "додай ще один товар"}]
    delegated = Command(update={"step_number": 2}, goto="end")

    with patch(
        "src.agents.langgraph.nodes.helpers.payment.delivery.ensure_prices_from_catalog",
        new=AsyncMock(return_value=state["selected_products"]),
    ), patch(
        "src.agents.langgraph.rules.product_addition.detect_product_addition_intent",
        return_value=True,
    ), patch(
        "src.agents.langgraph.rules.payment_proof.detect_payment_proof",
        return_value=True,
    ) as proof_mock, patch(
        "src.agents.langgraph.nodes.helpers.payment.delivery._delegate_to_llm",
        new=AsyncMock(return_value=delegated),
    ) as delegate_mock:
        result = await handle_delivery_data(state=state, runner=None, session_id="state5_scenario")

    assert result is delegated
    proof_mock.assert_not_called()
    delegate_mock.assert_awaited_once()


def test_state5_off_topic_question_keeps_state5_and_routes_agent():
    text = "які у вас сукні ще є"
    detected = detect_intent_from_text(
        text,
        has_image=False,
        current_state=State.STATE_5_PAYMENT_DELIVERY.value,
    )
    assert detected == "PRODUCT_CATEGORY"

    route = route_after_intent(
        {
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "detected_intent": detected,
            "selected_products": [{"name": "Тест"}],
        }
    )
    assert route == "agent"

    state = _base_state()
    state["detected_intent"] = detected
    response = SupportResponse(
        event="simple_answer",
        messages=[MessageItem(type="text", content="dummy")],
        products=[],
        metadata=ResponseMetadata(
            session_id="state5_scenario",
            current_state=State.STATE_7_END.value,
            intent="THANKYOU_SMALLTALK",
            escalation_level="NONE",
        ),
    )
    new_state, _, _ = finalize_transition(state, response, text)
    assert new_state == State.STATE_5_PAYMENT_DELIVERY.value
