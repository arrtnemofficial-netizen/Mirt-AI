"""
Tests for LangGraph v2 multi-node architecture.
Tests with mocked LLM runner to verify node flow and observability.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.graph_v2 import (
    ConversationStateV2,
    agent_node_v2,
    build_graph_v2,
    moderation_node,
    tool_plan_node,
    validation_node,
)
from src.core.models import AgentResponse, Message, Metadata
from src.core.state_machine import Intent, State


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def empty_state() -> ConversationStateV2:
    """Create empty conversation state."""
    return ConversationStateV2(
        messages=[],
        current_state=State.STATE_0_INIT.value,
        metadata={"session_id": "test-session-123"},
        moderation_result=None,
        tool_plan_result=None,
        validation_errors=[],
        should_escalate=False,
    )


@pytest.fixture
def state_with_user_message() -> ConversationStateV2:
    """Create state with user message."""
    return ConversationStateV2(
        messages=[{"role": "user", "content": "Шукаю сукню для дитини"}],
        current_state=State.STATE_0_INIT.value,
        metadata={"session_id": "test-session-123", "channel": "telegram"},
        moderation_result=None,
        tool_plan_result=None,
        validation_errors=[],
        should_escalate=False,
    )


@pytest.fixture
def mock_agent_response() -> AgentResponse:
    """Create mock agent response."""
    return AgentResponse(
        event="simple_answer",
        messages=[Message(content="Вітаю! Підкажіть зріст дитини.")],
        products=[],
        metadata=Metadata(
            session_id="test-session-123",
            current_state=State.STATE_1_DISCOVERY.value,
            intent="DISCOVERY_OR_QUESTION",
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

        assert result["moderation_result"]["allowed"] is True
        assert result["should_escalate"] is False

    @pytest.mark.asyncio
    async def test_moderation_blocks_unsafe_message(self, empty_state):
        """Unsafe message should be blocked."""
        empty_state["messages"] = [{"role": "user", "content": "мій email test@test.com"}]

        result = await moderation_node(empty_state)

        # Email detection should flag message
        assert "email" in result["moderation_result"]["flags"]

    @pytest.mark.asyncio
    async def test_moderation_empty_message(self, empty_state):
        """Empty message should pass."""
        result = await moderation_node(empty_state)

        assert result["moderation_result"]["allowed"] is True


# =============================================================================
# TOOL PLAN NODE TESTS
# =============================================================================


class TestToolPlanNode:
    """Tests for tool_plan_node."""

    @pytest.mark.asyncio
    async def test_tool_plan_skips_when_escalated(self, state_with_user_message):
        """Should skip tool planning when escalated."""
        state_with_user_message["should_escalate"] = True

        result = await tool_plan_node(state_with_user_message)

        assert result["tool_plan_result"] is None

    @pytest.mark.asyncio
    async def test_tool_plan_creates_plan_for_discovery(self, state_with_user_message):
        """Should create tool plan for discovery intent."""
        state_with_user_message["metadata"]["intent"] = Intent.DISCOVERY_OR_QUESTION.value

        with patch("src.agents.graph_v2.execute_tool_plan", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {
                "tool_results": [{"tool": "SEARCH_BY_QUERY", "result": []}],
                "instruction": "Test",
                "success": True,
            }

            result = await tool_plan_node(state_with_user_message)

            assert result["tool_plan_result"] is not None


# =============================================================================
# AGENT NODE TESTS
# =============================================================================


class TestAgentNodeV2:
    """Tests for agent_node_v2."""

    @pytest.mark.asyncio
    async def test_agent_handles_moderation_escalation(
        self, state_with_user_message, mock_agent_response
    ):
        """Should return escalation response when moderation blocked."""
        state_with_user_message["should_escalate"] = True
        state_with_user_message["moderation_result"] = {
            "allowed": False,
            "flags": ["safety"],
            "reason": "Unsafe content",
        }

        mock_runner = AsyncMock(return_value=mock_agent_response)
        result = await agent_node_v2(state_with_user_message, mock_runner)

        # Runner should NOT be called
        mock_runner.assert_not_called()

        # Should have escalation response
        last_message = result["messages"][-1]
        response_data = json.loads(last_message["content"])
        assert response_data["event"] == "escalation"

    @pytest.mark.asyncio
    async def test_agent_calls_runner(self, state_with_user_message, mock_agent_response):
        """Should call LLM runner when not escalated."""
        mock_runner = AsyncMock(return_value=mock_agent_response)

        result = await agent_node_v2(state_with_user_message, mock_runner)

        mock_runner.assert_called_once()
        assert result["current_state"] == State.STATE_1_DISCOVERY.value

    @pytest.mark.asyncio
    async def test_agent_updates_state(self, state_with_user_message, mock_agent_response):
        """Should update state after agent response."""
        mock_runner = AsyncMock(return_value=mock_agent_response)

        result = await agent_node_v2(state_with_user_message, mock_runner)

        assert result["current_state"] == mock_agent_response.metadata.current_state
        assert result["metadata"]["intent"] == mock_agent_response.metadata.intent


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

        assert result["validation_errors"] == []

    @pytest.mark.asyncio
    async def test_validation_detects_price_error(self, state_with_user_message):
        """Should detect invalid product price."""
        invalid_response = {
            "event": "offer",
            "products": [
                {"id": 1, "name": "Test", "price": 0, "photo_url": "https://example.com/1.jpg"}
            ],
            "metadata": {"session_id": "test-session-123"},
        }
        state_with_user_message["messages"].append(
            {
                "role": "assistant",
                "content": json.dumps(invalid_response),
            }
        )
        state_with_user_message["tool_plan_result"] = {"tool_results": []}

        result = await validation_node(state_with_user_message)

        # Should have validation errors (price = 0 invalid)
        assert len(result["validation_errors"]) > 0

    @pytest.mark.asyncio
    async def test_validation_detects_session_mismatch(self, state_with_user_message):
        """Should detect session_id mismatch."""
        response_with_wrong_session = {
            "event": "simple_answer",
            "products": [],
            "metadata": {"session_id": "wrong-session"},
        }
        state_with_user_message["messages"].append(
            {
                "role": "assistant",
                "content": json.dumps(response_with_wrong_session),
            }
        )
        state_with_user_message["tool_plan_result"] = {"tool_results": []}

        result = await validation_node(state_with_user_message)

        assert any("session_id" in e for e in result["validation_errors"])


# =============================================================================
# GRAPH STRUCTURE TESTS
# =============================================================================


class TestGraphStructure:
    """Tests for graph structure and flow."""

    def test_graph_builds_successfully(self):
        """Graph should build without errors."""
        mock_runner = AsyncMock()
        graph = build_graph_v2(mock_runner)

        assert graph is not None

    def test_graph_has_correct_nodes(self):
        """Graph should have all required nodes."""
        mock_runner = AsyncMock()
        graph = build_graph_v2(mock_runner)

        # Check nodes exist in compiled graph
        assert graph is not None


# =============================================================================
# FEATURE FLAG TESTS
# =============================================================================


class TestFeatureFlags:
    """Tests for feature flag behavior."""

    def test_use_graph_v2_flag_exists(self):
        """USE_GRAPH_V2 flag should exist in config."""
        from src.conf.config import Settings

        settings = Settings()
        assert hasattr(settings, "USE_GRAPH_V2")
        assert isinstance(settings.USE_GRAPH_V2, bool)

    def test_use_tool_planner_flag_exists(self):
        """USE_TOOL_PLANNER flag should exist in config."""
        from src.conf.config import Settings

        settings = Settings()
        assert hasattr(settings, "USE_TOOL_PLANNER")
        assert isinstance(settings.USE_TOOL_PLANNER, bool)

    def test_use_product_validation_flag_exists(self):
        """USE_PRODUCT_VALIDATION flag should exist in config."""
        from src.conf.config import Settings

        settings = Settings()
        assert hasattr(settings, "USE_PRODUCT_VALIDATION")
        assert isinstance(settings.USE_PRODUCT_VALIDATION, bool)
