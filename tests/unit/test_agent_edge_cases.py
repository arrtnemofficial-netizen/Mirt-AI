"""Unit tests for edge cases in agent functions."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.agents.pydantic.deps import AgentDeps
from src.agents.pydantic.exceptions import AgentValidationError
from src.agents.pydantic.models import (
    EscalationInfo,
    MessageItem,
    PaymentResponse,
    ResponseMetadata,
    SupportResponse,
    VisionResponse,
)
from src.agents.pydantic.payment_agent import run_payment
from src.agents.pydantic.support_agent import run_support
from src.agents.pydantic.vision_agent import run_vision


class TestAgentEdgeCases:
    """Test edge cases for all agents."""

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.llm_usage_logger.log_llm_usage_best_effort")
    async def test_agent_handles_none_message(
        self, mock_log_usage, mock_get_agent
    ):
        """Test that agents handle None message."""
        deps = AgentDeps(
            session_id="test_session",
            trace_id="test_trace",
            current_state="STATE_0_INIT",
        )

        # Setup mocks
        mock_agent = Mock()
        mock_get_agent.return_value = mock_agent

        # Call with None message - should raise validation error
        with pytest.raises(AgentValidationError, match="message cannot be None"):
            await run_support(None, deps)  # type: ignore

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.llm_usage_logger.log_llm_usage_best_effort")
    async def test_agent_handles_empty_message(
        self, mock_log_usage, mock_get_agent
    ):
        """Test that agents handle empty message."""
        deps = AgentDeps(
            session_id="test_session",
            trace_id="test_trace",
            current_state="STATE_0_INIT",
        )

        # Setup mocks
        mock_agent = Mock()
        mock_get_agent.return_value = mock_agent

        # Call with empty message - should raise validation error
        with pytest.raises(AgentValidationError, match="message cannot be empty"):
            await run_support("", deps)

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.llm_usage_logger.log_llm_usage_best_effort")
    async def test_agent_handles_none_deps(
        self, mock_log_usage, mock_get_agent
    ):
        """Test that agents handle None deps."""
        # Setup mocks
        mock_agent = Mock()
        mock_get_agent.return_value = mock_agent

        # Call with None deps - should raise validation error
        with pytest.raises(AgentValidationError, match="deps cannot be None"):
            await run_support("Привіт!", None)  # type: ignore

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.llm_usage_logger.log_llm_usage_best_effort")
    async def test_agent_handles_invalid_deps(
        self, mock_log_usage, mock_get_agent
    ):
        """Test that agents handle invalid deps."""
        # Create deps with missing required fields
        deps = AgentDeps(
            session_id="",  # Empty session_id
            trace_id="test_trace",
            current_state="STATE_0_INIT",
        )

        # Setup mocks
        mock_agent = Mock()
        mock_get_agent.return_value = mock_agent

        # Call function - should raise validation error
        with pytest.raises(AgentValidationError, match="session_id is required"):
            await run_support("Привіт!", deps)

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.llm_usage_logger.log_llm_usage_best_effort")
    async def test_agent_handles_none_message_history(
        self, mock_log_usage, mock_get_agent
    ):
        """Test that agents handle None message_history."""
        deps = AgentDeps(
            session_id="test_session",
            trace_id="test_trace",
            current_state="STATE_0_INIT",
        )

        # Setup mocks
        mock_agent = Mock()
        result = Mock()
        result.output = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Test")],
            metadata=ResponseMetadata(
                session_id="test_session",
                current_state="STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="NONE",
            ),
        )
        result.usage = None
        result.model_used = None
        mock_agent.run = AsyncMock(return_value=result)
        mock_get_agent.return_value = mock_agent

        # Call with None message_history - should work fine
        response = await run_support("Привіт!", deps, message_history=None)

        # Should not crash
        assert response is not None

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.llm_usage_logger.log_llm_usage_best_effort")
    async def test_agent_handles_llm_api_error(
        self, mock_log_usage, mock_get_agent
    ):
        """Test that agents handle LLM API errors."""
        deps = AgentDeps(
            session_id="test_session",
            trace_id="test_trace",
            current_state="STATE_0_INIT",
        )

        # Setup mocks to simulate LLM API error
        mock_agent = Mock()
        # Simulate OpenAI API error (rate limit, authentication, etc.)
        from openai import APIError

        mock_agent.run = AsyncMock(side_effect=APIError("Rate limit exceeded", request=None, body=None))
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_support("Привіт!", deps)

        # Should return escalation response, not crash
        assert response is not None
        assert response.event == "escalation"
        assert response.escalation is not None

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.support_agent.get_support_agent")
    @patch("src.services.llm_usage_logger.log_llm_usage_best_effort")
    async def test_agent_handles_network_error(
        self, mock_log_usage, mock_get_agent
    ):
        """Test that agents handle network errors."""
        deps = AgentDeps(
            session_id="test_session",
            trace_id="test_trace",
            current_state="STATE_0_INIT",
        )

        # Setup mocks to simulate network error
        mock_agent = Mock()
        import httpx

        mock_agent.run = AsyncMock(
            side_effect=httpx.NetworkError("Connection timeout")
        )
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_support("Привіт!", deps)

        # Should return escalation response, not crash
        assert response is not None
        assert response.event == "escalation"
        assert response.escalation is not None

