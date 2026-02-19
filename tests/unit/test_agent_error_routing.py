import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.agents.langgraph.nodes.agent import agent_node
from src.agents.langgraph.routers.post_process import route_after_agent


def _base_state() -> dict:
    return {
        "session_id": "s-1",
        "trace_id": "t-1",
        "current_state": "STATE_1_DISCOVERY",
        "dialog_phase": "ACTIVE",
        "messages": [{"role": "user", "content": "Привіт"}],
        "metadata": {},
        "selected_products": [],
        "step_number": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised_error", "expected_code", "expected_type", "expected_recoverable"),
    [
        (ValueError("invalid payload"), "AGENT_VALIDATION_ERROR", "validation", True),
        (httpx.ConnectError("provider down"), "AGENT_PROVIDER_UNAVAILABLE", "network_provider", True),
        (asyncio.TimeoutError("timeout"), "AGENT_TIMEOUT", "timeout", True),
        (RuntimeError("boom"), "AGENT_UNEXPECTED_ERROR", "unexpected", False),
    ],
)
async def test_agent_node_returns_structured_error_payload_by_category(
    raised_error: Exception,
    expected_code: str,
    expected_type: str,
    expected_recoverable: bool,
):
    state = _base_state()

    with (
        patch("src.agents.langgraph.nodes.agent.execute_agent_dispatch", new_callable=AsyncMock) as dispatch_mock,
        patch("src.agents.langgraph.nodes.agent.track_metric") as metric_mock,
    ):
        dispatch_mock.side_effect = raised_error

        result = await agent_node(state)

    assert result["current_state"] == "STATE_1_DISCOVERY"
    assert result["last_error"] == expected_code
    assert "agent_error" in result
    assert result["agent_error"]["error_code"] == expected_code
    assert result["agent_error"]["error_type"] == expected_type
    assert result["agent_error"]["recoverable"] is expected_recoverable
    assert result["agent_response"]["agent_error"]["error_code"] == expected_code

    metric_mock.assert_called_once()
    metric_name, metric_value, metric_tags = metric_mock.call_args.args
    assert metric_name == "agent_errors_total"
    assert metric_value == 1
    assert metric_tags["error_code"] == expected_code
    assert metric_tags["error_type"] == expected_type


def test_route_after_agent_recoverable_error_goes_to_validation():
    route = route_after_agent(
        {
            "session_id": "s-1",
            "agent_response": {
                "agent_error": {
                    "error_code": "AGENT_PROVIDER_UNAVAILABLE",
                    "recoverable": True,
                }
            },
        }
    )
    assert route == "validation"


def test_route_after_agent_non_recoverable_error_goes_to_escalation():
    route = route_after_agent(
        {
            "session_id": "s-1",
            "agent_response": {
                "agent_error": {
                    "error_code": "AGENT_UNEXPECTED_ERROR",
                    "recoverable": False,
                }
            },
        }
    )
    assert route == "escalation"
