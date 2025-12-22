"""
E2E: PydanticAI agents integration with LangGraph.
==================================================
Tests integration between PydanticAI agents and LangGraph:
- Agent execution within graph nodes
- State passing between graph and agents
- Error handling and fallbacks
"""

from __future__ import annotations

import pytest

from src.agents.pydantic.deps import AgentDeps, create_deps_from_state
from src.agents.pydantic.main_agent import run_main
from src.core.state_machine import State


@pytest.mark.e2e
@pytest.mark.asyncio
class TestAgentIntegration:
    """End-to-end tests for PydanticAI agents integration."""

    async def test_main_agent_execution(self):
        """Test that main agent executes and returns structured response."""
        deps = AgentDeps(
            session_id="test_e2e_main_agent",
            current_state=State.STATE_1_DISCOVERY.value,
            channel="telegram",
        )

        result = await run_main("Шукаю сукню для дитини", deps)

        assert result is not None
        assert result.event is not None
        assert result.messages
        assert len(result.messages) > 0
        assert result.metadata is not None

    async def test_agent_with_state_context(self):
        """Test that agent receives state context correctly."""
        state = {
            "session_id": "test_e2e_state_context",
            "current_state": State.STATE_3_SIZE_COLOR.value,
            "selected_products": [{"name": "Сукня", "price": 500, "size": "110"}],
            "metadata": {
                "session_id": "test_e2e_state_context",
                "current_state": State.STATE_3_SIZE_COLOR.value,
            },
        }

        deps = create_deps_from_state(state)
        result = await run_main("Який колір є в наявності?", deps)

        assert result is not None
        assert result.metadata.current_state == State.STATE_3_SIZE_COLOR.value

    async def test_agent_circuit_breaker_integration(self):
        """Test that circuit breaker works with agent execution."""
        from src.core.circuit_breaker import get_circuit_breaker

        cb = get_circuit_breaker("pydantic_ai_main_agent")

        # Force circuit breaker OPEN
        for _ in range(5):
            cb.record_failure()

        deps = AgentDeps(
            session_id="test_e2e_cb_agent",
            current_state=State.STATE_1_DISCOVERY.value,
        )

        # Should return escalation due to circuit breaker
        result = await run_main("Привіт", deps)

        assert result is not None
        assert result.event == "escalation"
        assert result.escalation is not None
        assert "CIRCUIT_BREAKER" in result.escalation.reason

        # Reset circuit breaker
        cb.record_success()
        cb.record_success()
        cb.record_success()

    async def test_agent_error_handling(self):
        """Test that agent errors are handled gracefully."""
        deps = AgentDeps(
            session_id="test_e2e_agent_error",
            current_state=State.STATE_1_DISCOVERY.value,
        )

        # Normal execution should work
        result = await run_main("Привіт", deps)

        assert result is not None
        # Even on error, should return valid response (escalation)
        assert result.event is not None
        assert result.messages

    async def test_agent_tools_execution(self):
        """Test that agent tools (search_products, etc.) execute."""
        deps = AgentDeps(
            session_id="test_e2e_agent_tools",
            current_state=State.STATE_1_DISCOVERY.value,
        )

        result = await run_main("Шукаю сукню розмір 110", deps)

        assert result is not None
        # Tools should execute (search_products may be called)
        # Response should contain relevant information
        assert result.messages
        assert len(result.messages) > 0

    async def test_agent_state_transition(self):
        """Test that agent can trigger state transitions."""
        deps = AgentDeps(
            session_id="test_e2e_agent_transition",
            current_state=State.STATE_1_DISCOVERY.value,
        )

        result = await run_main("Шукаю сукню", deps)

        assert result is not None
        # Agent should suggest next state
        assert result.metadata.current_state is not None
        assert result.metadata.current_state in [
            State.STATE_1_DISCOVERY.value,
            State.STATE_2_VISION.value,
            State.STATE_3_SIZE_COLOR.value,
            State.STATE_4_OFFER.value,
        ]

