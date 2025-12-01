"""
Tests for LangGraph Production Architecture.
Tests with mocked LLM runner to verify node flow and observability.

Updated to use NEW architecture:
- src.agents.langgraph (graph, state, nodes, edges)
- src.agents.pydantic (agents, models, deps)
"""

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.agents import (
    ConversationState,
    create_initial_state,
    AgentDeps,
    SupportResponse,
    ProductMatch,
    MessageItem,
    ResponseMetadata,
)
from src.agents.langgraph.graph import build_production_graph
from src.agents.langgraph.nodes import (
    moderation_node,
    validation_node,
    agent_node,
)
from src.core.state_machine import State


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def empty_state() -> dict[str, Any]:
    """Create empty conversation state."""
    return create_initial_state(
        session_id="test-session-123",
        messages=[],
        metadata={"channel": "test"},
    )


@pytest.fixture
def state_with_user_message() -> dict[str, Any]:
    """Create state with user message."""
    return create_initial_state(
        session_id="test-session-123",
        messages=[{"role": "user", "content": "Шукаю сукню для дитини"}],
        metadata={"channel": "telegram"},
    )


@pytest.fixture
def mock_support_response() -> SupportResponse:
    """Create mock PydanticAI agent response."""
    return SupportResponse(
        event="simple_answer",
        messages=[MessageItem(content="Вітаю! Підкажіть зріст дитини.")],
        products=[],
        metadata=ResponseMetadata(
            session_id="test-session-123",
            current_state="STATE_1_DISCOVERY",
            intent="DISCOVERY_OR_QUESTION",
            escalation_level="NONE",
        ),
    )


# =============================================================================
# MODERATION NODE TESTS
# =============================================================================


class TestModerationNode:
    """Tests for moderation_node."""

    @pytest.mark.asyncio
    async def test_moderation_allows_safe_message(self, state_with_user_message):
        """Safe message should pass moderation."""
        result = await moderation_node(state_with_user_message)

        assert result.get("moderation_result", {}).get("allowed", True) is True
        assert result.get("should_escalate", False) is False

    @pytest.mark.asyncio
    async def test_moderation_handles_empty_messages(self, empty_state):
        """Empty message should be handled gracefully."""
        result = await moderation_node(empty_state)

        # Should not crash
        assert "moderation_result" in result or "should_escalate" in result

    @pytest.mark.asyncio
    async def test_moderation_flags_email(self, state_with_user_message):
        """Email in message should be flagged."""
        state_with_user_message["messages"] = [
            {"role": "user", "content": "мій email test@test.com"}
        ]

        result = await moderation_node(state_with_user_message)

        # Should detect email
        flags = result.get("moderation_result", {}).get("flags", [])
        assert "email" in flags or len(flags) > 0


# =============================================================================
# VALIDATION NODE TESTS
# =============================================================================


class TestValidationNode:
    """Tests for validation_node."""

    @pytest.mark.asyncio
    async def test_validation_skips_when_escalated(self, state_with_user_message):
        """Should skip validation when escalated."""
        state_with_user_message["should_escalate"] = True

        result = await validation_node(state_with_user_message)

        # Should return empty errors when escalated
        assert result.get("validation_errors", []) == []

    @pytest.mark.asyncio
    async def test_validation_passes_valid_response(self, state_with_user_message):
        """Valid response should pass validation."""
        valid_response = {
            "event": "simple_answer",
            "messages": [{"type": "text", "content": "Test response"}],
            "products": [],
            "metadata": {
                "session_id": "test-session-123",
                "current_state": "STATE_1_DISCOVERY",
                "intent": "DISCOVERY_OR_QUESTION",
                "escalation_level": "NONE",
            },
        }
        state_with_user_message["agent_response"] = valid_response

        result = await validation_node(state_with_user_message)

        # Should have no validation errors
        assert len(result.get("validation_errors", [])) == 0


# =============================================================================
# AGENT NODE TESTS
# =============================================================================


class TestAgentNode:
    """Tests for agent_node with mocked PydanticAI."""

    @pytest.mark.asyncio
    async def test_agent_node_returns_state_update(self, state_with_user_message):
        """Agent node should return valid state update."""
        # Create mock response
        mock_response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(content="Вітаю! Чим допомогти?")],
            products=[],
            metadata=ResponseMetadata(
                session_id="test-session-123",
                current_state="STATE_1_DISCOVERY",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

        with patch("src.agents.langgraph.nodes.agent.run_support", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_response

            result = await agent_node(state_with_user_message)

            # Should update state
            assert "current_state" in result or "agent_response" in result

    @pytest.mark.asyncio
    async def test_agent_node_handles_error(self, state_with_user_message):
        """Agent node should handle errors gracefully."""
        with patch("src.agents.langgraph.nodes.agent.run_support", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = Exception("Test error")

            result = await agent_node(state_with_user_message)

            # Should return error state
            assert "last_error" in result or "retry_count" in result


# =============================================================================
# GRAPH STRUCTURE TESTS
# =============================================================================


class TestGraphStructure:
    """Tests for graph structure and flow."""

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

    def test_graph_has_correct_nodes(self):
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
# PYDANTIC MODELS TESTS
# =============================================================================


class TestPydanticModels:
    """Tests for PydanticAI output models."""

    def test_support_response_validation(self):
        """SupportResponse should validate correctly."""
        response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(content="Test message")],
            metadata=ResponseMetadata(
                session_id="test",
                current_state="STATE_0_INIT",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
            products=[],
        )

        assert response.event == "simple_answer"
        assert len(response.messages) == 1
        assert response.metadata.current_state == "STATE_0_INIT"

    def test_product_match_requires_https(self):
        """ProductMatch should reject non-https URLs."""
        with pytest.raises(ValueError):
            ProductMatch(
                id=123,
                name="Test",
                price=100,
                size="M",
                color="red",
                photo_url="http://not-https.com/photo.jpg",  # Should fail
            )

    def test_product_match_accepts_https(self):
        """ProductMatch should accept https URLs."""
        product = ProductMatch(
            id=3443041,
            name="Сукня Анна",
            price=1850,
            size="122-128",
            color="голубий",
            photo_url="https://cdn.sitniks.com/test.jpg",
        )

        assert product.name == "Сукня Анна"
        assert product.price == 1850

    def test_message_item_max_length(self):
        """MessageItem should enforce max length."""
        with pytest.raises(ValueError):
            MessageItem(content="x" * 1000)  # > 900 chars

    def test_agent_deps_from_state(self):
        """AgentDeps should be created from state correctly."""
        from src.agents import create_deps_from_state

        state = create_initial_state(
            session_id="test-123",
            messages=[],
            metadata={"channel": "instagram", "customer_name": "Марія"},
        )

        deps = create_deps_from_state(state)

        assert deps.session_id == "test-123"
        assert deps.channel == "instagram"
        assert deps.customer_name == "Марія"


# =============================================================================
# STATE MANAGEMENT TESTS
# =============================================================================


class TestStateManagement:
    """Tests for state creation and management."""

    def test_create_initial_state(self):
        """Should create valid initial state."""
        state = create_initial_state(
            session_id="test-456",
            messages=[{"role": "user", "content": "Hi"}],
            metadata={"channel": "telegram"},
        )

        assert state["session_id"] == "test-456"
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
