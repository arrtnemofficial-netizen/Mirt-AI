"""Regression tests for validation node runtime safeguards."""

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_validation_autonormalize_inconsistent_phase_without_name_error():
    """Inconsistent state/phase auto-fix must not crash when State import path executes."""
    from src.agents.langgraph.nodes.validation import validation_node

    state = {
        "session_id": "sess_validation",
        "current_state": "STATE_1_DISCOVERY",
        "dialog_phase": "INIT",
        "metadata": {},
        "messages": [],
        "step_number": 3,
    }

    with patch(
        "src.agents.langgraph.nodes.validation.validate_state",
        return_value=["Inconsistent state/phase: STATE_1_DISCOVERY vs INIT"],
    ):
        result = await validation_node(state)

    assert result["step_number"] == 4
    assert result.get("dialog_phase") == "DISCOVERY"


@pytest.mark.asyncio
async def test_validation_autonormalize_failure_emits_fallback_metric():
    """If phase auto-fix fails, node must not crash and should emit fallback metric."""
    from src.agents.langgraph.nodes.validation import validation_node

    state = {
        "session_id": "sess_validation_fallback",
        "current_state": "STATE_UNKNOWN",
        "dialog_phase": "INIT",
        "metadata": {},
        "messages": [],
        "step_number": 10,
    }

    with (
        patch(
            "src.agents.langgraph.nodes.validation.validate_state",
            return_value=["Inconsistent state/phase: STATE_UNKNOWN vs INIT"],
        ),
        patch(
            "src.agents.langgraph.nodes.validation.State.from_string",
            side_effect=ValueError("bad state"),
        ),
        patch("src.agents.langgraph.nodes.validation.track_metric") as metric_mock,
    ):
        result = await validation_node(state)

    assert result["step_number"] == 11
    assert any(
        call.args and call.args[0] == "fallback_triggered"
        for call in metric_mock.call_args_list
    )
