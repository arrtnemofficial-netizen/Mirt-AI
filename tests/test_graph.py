"""
Tests for LangGraph production graph.
=====================================
Updated for new architecture with build_production_graph.
"""

import pytest
from unittest.mock import patch, AsyncMock

from src.agents import (
    build_production_graph,
    create_initial_state,
    ConversationState,
    SupportResponse,
    MessageItem,
    ResponseMetadata,
)
from src.agents.langgraph.nodes import moderation_node


# =============================================================================
# GRAPH STRUCTURE TESTS
# =============================================================================


class TestGraphStructure:
    """Tests for graph structure and building."""

    def test_graph_builds_successfully(self):
        """Graph should build without errors."""
        async def mock_runner(msg: str, metadata: dict) -> dict:
            return {
                "event": "simple_answer",
                "messages": [{"type": "text", "content": "test"}],
                "products": [],
                "metadata": {
                    "session_id": "",
                    "current_state": "STATE_0_INIT",
                    "intent": "GREETING_ONLY",
                    "escalation_level": "NONE",
                },
            }

        graph = build_production_graph(mock_runner)
        assert graph is not None

    def test_graph_has_required_nodes(self):
        """Graph should have all required nodes."""
        async def mock_runner(msg: str, metadata: dict) -> dict:
            return {}

        graph = build_production_graph(mock_runner)

        # Check nodes exist
        node_names = list(graph.nodes.keys()) if hasattr(graph, 'nodes') else []

        expected_nodes = ["moderation", "intent", "agent", "validation", "escalation"]
        for node in expected_nodes:
            assert node in node_names, f"Node '{node}' not found in graph"


# =============================================================================
# MODERATION NODE TESTS
# =============================================================================


class TestModerationNode:
    """Tests for moderation node functionality."""

    @pytest.mark.asyncio
    async def test_moderation_allows_safe_message(self):
        """Safe message should pass moderation."""
        state = create_initial_state(
            session_id="test-123",
            messages=[{"role": "user", "content": "Привіт, шукаю сукню"}],
        )

        result = await moderation_node(state)

        assert result.get("moderation_result", {}).get("allowed", True) is True
        assert result.get("should_escalate", False) is False

    @pytest.mark.asyncio
    async def test_moderation_handles_empty_messages(self):
        """Empty message should be handled gracefully."""
        state = create_initial_state(
            session_id="test-456",
            messages=[],
        )

        result = await moderation_node(state)

        # Should not crash
        assert "moderation_result" in result or "step_number" in result

    @pytest.mark.asyncio
    async def test_moderation_flags_pii(self):
        """PII in message should be flagged."""
        state = create_initial_state(
            session_id="test-789",
            messages=[{"role": "user", "content": "мій email test@test.com"}],
        )

        result = await moderation_node(state)

        # Should detect email
        flags = result.get("moderation_result", {}).get("flags", [])
        assert "email" in flags or len(flags) > 0


# =============================================================================
# STATE FLOW TESTS
# =============================================================================


class TestStateFlow:
    """Tests for state transitions in graph."""

    def test_create_initial_state(self):
        """Should create valid initial state."""
        state = create_initial_state(
            session_id="test-flow",
            messages=[{"role": "user", "content": "Привіт"}],
            metadata={"channel": "telegram"},
        )

        assert state["session_id"] == "test-flow"
        assert state["current_state"] == "STATE_0_INIT"
        assert len(state["messages"]) == 1

    def test_state_has_required_fields(self):
        """State should have all required fields."""
        state = create_initial_state(session_id="test")

        required_fields = [
            "session_id",
            "current_state",
            "messages",
            "metadata",
            "should_escalate",
            "validation_errors",
            "retry_count",
            "max_retries",
        ]

        for field in required_fields:
            assert field in state, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_moderation_to_intent_flow(self):
        """Test state flows correctly from moderation to intent."""
        from src.agents.langgraph.nodes import intent_detection_node

        state = create_initial_state(
            session_id="flow-test",
            messages=[{"role": "user", "content": "Привіт!"}],
        )

        # Step 1: Moderation
        mod_output = await moderation_node(state)
        assert mod_output["moderation_result"]["allowed"] is True

        # Merge output into state
        state.update(mod_output)

        # Step 2: Intent
        intent_output = await intent_detection_node(state)
        assert "detected_intent" in intent_output

        # State should still have messages
        assert "messages" in state
        assert len(state["messages"]) > 0
