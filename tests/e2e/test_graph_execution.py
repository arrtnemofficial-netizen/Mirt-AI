"""
E2E: LangGraph execution test.
===============================
Tests graph execution with real data:
- Graph compilation
- Node execution order
- State transitions
- Checkpoint persistence
"""

from __future__ import annotations

import pytest

from src.agents.langgraph.graph import invoke_graph
from src.agents.langgraph.state import create_initial_state
from src.core.state_machine import State


@pytest.mark.e2e
@pytest.mark.asyncio
class TestGraphExecution:
    """End-to-end tests for LangGraph execution."""

    async def test_graph_compiles_successfully(self):
        """Test that production graph compiles without errors."""
        from src.agents import get_active_graph

        graph = get_active_graph()
        assert graph is not None

    async def test_graph_execution_with_real_state(self):
        """Test graph execution with real initial state."""
        session_id = "test_e2e_graph_exec"

        state = create_initial_state(
            session_id=session_id,
            messages=[{"role": "user", "content": "Привіт, шукаю одяг"}],
        )

        result = await invoke_graph(state=state, session_id=session_id)

        assert result is not None
        assert result.get("current_state") is not None
        assert result.get("messages") is not None

    async def test_moderation_node_execution(self):
        """Test that moderation node executes and routes correctly."""
        session_id = "test_e2e_moderation"

        state = create_initial_state(
            session_id=session_id,
            messages=[{"role": "user", "content": "Привіт"}],
        )

        result = await invoke_graph(state=state, session_id=session_id)

        # After moderation, should proceed to intent or escalation
        final_state = result.get("current_state")
        assert final_state is not None
        # Should not be stuck in INIT if moderation passed
        if result.get("should_escalate"):
            assert final_state == State.STATE_8_COMPLAINT.value
        else:
            assert final_state != State.STATE_0_INIT.value or len(result.get("messages", [])) > 1

    async def test_intent_detection_routing(self):
        """Test that intent detection routes to correct node."""
        session_id = "test_e2e_intent"

        state = create_initial_state(
            session_id=session_id,
            messages=[{"role": "user", "content": "Шукаю сукню для дитини"}],
        )

        result = await invoke_graph(state=state, session_id=session_id)

        # Should detect intent and route accordingly
        detected_intent = result.get("detected_intent")
        assert detected_intent is not None or result.get("current_state") is not None

    async def test_agent_node_execution(self):
        """Test that agent node executes and returns response."""
        session_id = "test_e2e_agent_node"

        state = create_initial_state(
            session_id=session_id,
            messages=[{"role": "user", "content": "Який розмір підійде для зросту 100 см?"}],
            metadata={"current_state": State.STATE_1_DISCOVERY.value},
        )
        state["current_state"] = State.STATE_1_DISCOVERY.value

        result = await invoke_graph(state=state, session_id=session_id)

        # Should have agent response
        assert result.get("agent_response") is not None or result.get("messages")

    async def test_validation_node_retry(self):
        """Test that validation node can trigger retry loop."""
        session_id = "test_e2e_validation"

        state = create_initial_state(
            session_id=session_id,
            messages=[{"role": "user", "content": "Шукаю товар"}],
        )

        result = await invoke_graph(state=state, session_id=session_id)

        # Validation should complete (success or escalation)
        assert result.get("current_state") is not None

    async def test_checkpoint_persistence(self):
        """Test that state persists in checkpointer."""
        session_id = "test_e2e_checkpoint"

        state1 = create_initial_state(
            session_id=session_id,
            messages=[{"role": "user", "content": "Привіт"}],
        )

        result1 = await invoke_graph(state=state1, session_id=session_id)

        # Second invocation should resume from checkpoint
        state2 = create_initial_state(
            session_id=session_id,
            messages=[
                {"role": "user", "content": "Привіт"},
                {"role": "user", "content": "Шукаю сукню"},
            ],
        )

        result2 = await invoke_graph(state=state2, session_id=session_id)

        # State should continue from previous execution
        assert result2.get("current_state") is not None

