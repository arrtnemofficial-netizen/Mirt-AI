"""
Regression tests for offer_node crash fix.
=========================================
Ensures:
1. No NameError when logging SSOT Transition (current_state was undefined)
2. Error path handles state without tool_errors (legacy checkpoints)
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.agents.langgraph.nodes.offer import offer_node
from src.agents.langgraph.state import create_initial_state
from src.core.state_machine import State


@pytest.fixture
def base_offer_state():
    """Base state for offer node tests."""
    return {
        "session_id": "test-offer-session",
        "current_state": State.STATE_4_OFFER.value,
        "dialog_phase": "OFFER_MADE",
        "messages": [{"role": "user", "content": "Беру!"}],
        "metadata": {"session_id": "test-offer-session"},
        "selected_products": [{"name": "Костюм Лагуна", "price": 2190, "size": "122-128"}],
        "detected_intent": "PAYMENT_DELIVERY",
        "has_image": False,
        "step_number": 5,
    }


def _make_support_response():
    """Minimal SupportResponse for offer_node success path."""
    from src.agents.pydantic.models import SupportResponse, ResponseMetadata, MessageItem
    return SupportResponse(
        event="simple_answer",
        messages=[MessageItem(type="text", content="Ось реквізити для оплати")],
        metadata=ResponseMetadata(
            session_id="test",
            current_state=State.STATE_5_PAYMENT_DELIVERY.value,
            intent="PAYMENT_DELIVERY",
            escalation_level="NONE",
        ),
        products=[],
        deliberation=None,
    )


@pytest.mark.asyncio
async def test_offer_node_no_name_error_success_path(base_offer_state):
    """REGRESSION: offer_node must not raise NameError when logging SSOT Transition."""
    with (
        patch("src.agents.langgraph.nodes.offer.run_support", new_callable=AsyncMock) as mock_run,
        patch("src.agents.langgraph.nodes.offer.settings") as mock_settings,
    ):
        mock_settings.DEBUG_TRACE_LOGS = False
        mock_settings.USE_OFFER_DELIBERATION = False
        mock_run.return_value = _make_support_response()

        result = await offer_node(base_offer_state, runner=None)

        assert "current_state" in result
        assert result["current_state"] == State.STATE_5_PAYMENT_DELIVERY.value
        assert "messages" in result
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_offer_node_error_path_handles_missing_tool_errors(base_offer_state):
    """REGRESSION: When run_support raises, state without tool_errors must not cause AttributeError."""
    # Simulate legacy checkpoint: dict state without tool_errors key
    state = {k: v for k, v in base_offer_state.items() if k != "tool_errors"}
    assert "tool_errors" not in state

    with (
        patch("src.agents.langgraph.nodes.offer.run_support", new_callable=AsyncMock) as mock_run,
        patch("src.agents.langgraph.nodes.offer.settings") as mock_settings,
    ):
        mock_settings.DEBUG_TRACE_LOGS = False
        mock_settings.USE_OFFER_DELIBERATION = False
        mock_run.side_effect = Exception("Simulated LLM failure")

        result = await offer_node(state, runner=None)

        assert "last_error" in result
        assert "Simulated LLM failure" in result["last_error"]
        assert "tool_errors" in result
        assert any("Offer error" in e for e in result["tool_errors"])
        assert result.get("retry_count", 0) >= 1


@pytest.mark.asyncio
async def test_offer_node_error_path_with_conversation_state():
    """REGRESSION: ConversationState (Pydantic) without tool_errors in extra must not crash."""
    state_obj = create_initial_state(session_id="test", messages=[{"role": "user", "content": "x"}])
    # Override to offer context
    state_obj.current_state = State.STATE_4_OFFER.value
    state_obj.selected_products = [{"name": "Test", "price": 100, "size": "128"}]
    state_obj.detected_intent = "PAYMENT_DELIVERY"
    # Ensure tool_errors exists (we added it to StateSchema)
    assert hasattr(state_obj, "tool_errors") or "tool_errors" in state_obj

    # Convert to dict for offer_node (LangGraph typically passes dict)
    state_dict = dict(state_obj)
    state_dict["messages"] = [{"role": "user", "content": "Беру"}]

    with (
        patch("src.agents.langgraph.nodes.offer.run_support", new_callable=AsyncMock) as mock_run,
        patch("src.agents.langgraph.nodes.offer.settings") as mock_settings,
    ):
        mock_settings.DEBUG_TRACE_LOGS = False
        mock_settings.USE_OFFER_DELIBERATION = False
        mock_run.side_effect = RuntimeError("Test error")

        result = await offer_node(state_dict, runner=None)

        assert "last_error" in result
        assert "tool_errors" in result
