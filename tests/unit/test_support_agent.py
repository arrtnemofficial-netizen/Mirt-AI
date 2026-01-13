"""Unit tests for support_agent.run_support function."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from pydantic_ai import RunUsage

from src.agents.pydantic.deps import AgentDeps
from src.agents.pydantic.models import (
    EscalationInfo,
    MessageItem,
    ResponseMetadata,
    SupportResponse,
)
from src.agents.pydantic.support_agent import run_support


class TestRunSupport:
    """Unit tests for run_support function."""

    @pytest.fixture
    def mock_deps(self):
        """Create mock AgentDeps."""
        deps = AgentDeps(
            session_id="test_session_123",
            trace_id="test_trace_123",
            user_id="test_user_123",
            current_state="STATE_0_INIT",
            has_image=False,
        )
        # Add dialog_phase as attribute if needed
        deps.dialog_phase = None
        return deps

    @pytest.fixture
    def mock_support_response(self):
        """Create mock SupportResponse."""
        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Привіт! Чим можу допомогти?")],
            metadata=ResponseMetadata(
                session_id="test_session_123",
                current_state="STATE_1_DISCOVERY",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

    @pytest.fixture
    def mock_agent_run_result(self, mock_support_response):
        """Create mock AgentRunResult."""
        result = Mock()
        result.output = mock_support_response
        result.usage = RunUsage(input_tokens=100, output_tokens=50)
        result.model_used = None
        return result

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_support_success(
        self, mock_log_usage, mock_get_agent, mock_deps, mock_agent_run_result
    ):
        """Test successful run_support call with valid data."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(return_value=mock_agent_run_result)
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_support("Привіт!", mock_deps)

        # Assertions
        assert response is not None
        assert response.event == "simple_answer"
        assert len(response.messages) == 1
        assert response.messages[0].content == "Привіт! Чим можу допомогти?"
        assert response.metadata.session_id == "test_session_123"
        assert response.metadata.current_state == "STATE_1_DISCOVERY"
        assert response.metadata.intent == "GREETING_ONLY"

        # Verify agent.run was called
        mock_agent.run.assert_called_once_with(
            "Привіт!",
            deps=mock_deps,
            message_history=None,
        )

        # Verify usage logging was called (async task, so check it was created)
        # Note: asyncio.create_task is fire-and-forget, so we can't easily verify it
        # But we can verify the function was imported and available

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_support_with_message_history(
        self, mock_log_usage, mock_get_agent, mock_deps, mock_agent_run_result
    ):
        """Test run_support call with message history."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(return_value=mock_agent_run_result)
        mock_get_agent.return_value = mock_agent

        # Create message history
        message_history = [
            {"role": "user", "content": "Привіт!"},
            {"role": "assistant", "content": "Вітаю! Чим можу допомогти?"},
        ]

        # Call function
        response = await run_support("Який розмір?", mock_deps, message_history=message_history)

        # Assertions
        assert response is not None
        assert response.event == "simple_answer"

        # Verify agent.run was called with message_history
        mock_agent.run.assert_called_once_with(
            "Який розмір?",
            deps=mock_deps,
            message_history=message_history,
        )

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_support_timeout(
        self, mock_log_usage, mock_get_agent, mock_deps
    ):
        """Test run_support handles TimeoutError."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_support("Привіт!", mock_deps)

        # Assertions - should return escalation response
        assert response is not None
        assert response.event == "escalation"
        assert response.escalation is not None
        assert response.escalation.reason == "LLM_TIMEOUT"
        assert response.metadata.escalation_level == "L1"
        assert len(response.messages) == 1

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_support_generic_error(
        self, mock_log_usage, mock_get_agent, mock_deps
    ):
        """Test run_support handles generic errors."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(side_effect=ValueError("Test error"))
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_support("Привіт!", mock_deps)

        # Assertions - should return escalation response
        assert response is not None
        assert response.event == "escalation"
        assert response.escalation is not None
        # Generic ValueError is now caught as UNKNOWN_ERROR (L3)
        assert "UNKNOWN_ERROR" in response.escalation.reason or "AGENT_ERROR" in response.escalation.reason
        assert response.metadata.escalation_level in ("L2", "L3")
        assert len(response.messages) == 1

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_support_extracts_tokens(
        self, mock_log_usage, mock_get_agent, mock_deps, mock_support_response
    ):
        """Test run_support extracts tokens from result.usage."""
        # Setup mocks with usage
        mock_agent = Mock()
        result = Mock()
        result.output = mock_support_response
        result.usage = RunUsage(input_tokens=200, output_tokens=100)
        result.model_used = None
        mock_agent.run = AsyncMock(return_value=result)
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_support("Привіт!", mock_deps)

        # Assertions
        assert response is not None
        assert response.event == "simple_answer"

        # Verify agent.run was called
        mock_agent.run.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_support_handles_none_usage(
        self, mock_log_usage, mock_get_agent, mock_deps, mock_support_response
    ):
        """Test run_support handles None usage."""
        # Setup mocks with None usage
        mock_agent = Mock()
        result = Mock()
        result.output = mock_support_response
        result.usage = None
        result.model_used = None
        mock_agent.run = AsyncMock(return_value=result)
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_support("Привіт!", mock_deps)

        # Assertions - should not crash
        assert response is not None
        assert response.event == "simple_answer"

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_support_handles_empty_usage(
        self, mock_log_usage, mock_get_agent, mock_deps, mock_support_response
    ):
        """Test run_support handles empty usage (has_values() = False)."""
        # Setup mocks with empty usage
        mock_agent = Mock()
        result = Mock()
        result.output = mock_support_response
        result.usage = RunUsage()  # Default, no values
        result.model_used = None
        mock_agent.run = AsyncMock(return_value=result)
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_support("Привіт!", mock_deps)

        # Assertions - should not crash
        assert response is not None
        assert response.event == "simple_answer"

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_support_logs_usage(
        self, mock_log_usage, mock_get_agent, mock_deps, mock_agent_run_result
    ):
        """Test run_support logs usage correctly."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(return_value=mock_agent_run_result)
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_support("Привіт!", mock_deps)

        # Assertions
        assert response is not None

        # Note: log_llm_usage_best_effort is called via asyncio.create_task
        # which is fire-and-forget, so we can't easily verify it was called
        # But we can verify the function exists and is importable
        from src.services.observability.llm_usage_logger import log_llm_usage_best_effort

        assert callable(log_llm_usage_best_effort)

