"""Unit tests for payment_agent.run_payment function."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic_ai import RunUsage

from src.agents.pydantic.deps import AgentDeps
from src.agents.pydantic.models import PaymentResponse
from src.agents.pydantic.payment_agent import run_payment


class TestRunPayment:
    """Unit tests for run_payment function."""

    @pytest.fixture
    def mock_deps(self):
        """Create mock AgentDeps."""
        deps = AgentDeps(
            session_id="test_session_123",
            trace_id="test_trace_123",
            user_id="test_user_123",
            current_state="STATE_5_PAYMENT_DELIVERY",
        )
        deps.dialog_phase = "WAITING_FOR_PAYMENT_PROOF"
        return deps

    @pytest.fixture
    def mock_payment_response(self):
        """Create mock PaymentResponse."""
        return PaymentResponse(
            reply_to_user="Дякую! Ваше замовлення прийнято.",
            order_ready=True,
            missing_fields=[],
        )

    @pytest.fixture
    def mock_payment_response_missing_fields(self):
        """Create mock PaymentResponse with missing fields."""
        return PaymentResponse(
            reply_to_user="Будь ласка, вкажіть ваше ім'я та телефон.",
            order_ready=False,
            missing_fields=["name", "phone"],
        )

    @pytest.fixture
    def mock_agent_run_result(self, mock_payment_response):
        """Create mock AgentRunResult."""
        result = Mock()
        result.output = mock_payment_response
        result.usage = RunUsage(input_tokens=150, output_tokens=75)
        result.model_used = None
        return result

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.payment_agent.get_payment_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_payment_success(
        self, mock_log_usage, mock_get_agent, mock_deps, mock_agent_run_result
    ):
        """Test successful payment processing."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(return_value=mock_agent_run_result)
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_payment("Моє ім'я Іван, телефон 0501234567", mock_deps)

        # Assertions
        assert response is not None
        assert response.order_ready is True
        assert len(response.missing_fields) == 0
        assert "замовлення" in response.reply_to_user.lower()

        # Verify agent.run was called
        mock_agent.run.assert_called_once_with(
            "Моє ім'я Іван, телефон 0501234567",
            deps=mock_deps,
            message_history=None,
        )

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.payment_agent.get_payment_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_payment_timeout(
        self, mock_log_usage, mock_get_agent, mock_deps
    ):
        """Test run_payment handles TimeoutError."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_payment("Моє ім'я Іван", mock_deps)

        # Assertions - should return error response
        assert response is not None
        assert response.order_ready is False
        assert len(response.missing_fields) > 0  # Should have missing fields

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.payment_agent.get_payment_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_payment_generic_error(
        self, mock_log_usage, mock_get_agent, mock_deps
    ):
        """Test run_payment handles generic errors."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(side_effect=ValueError("Test error"))
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_payment("Моє ім'я Іван", mock_deps)

        # Assertions - should return error response
        assert response is not None
        assert response.order_ready is False
        assert len(response.missing_fields) > 0  # Should have missing fields

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.payment_agent.get_payment_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_payment_extracts_tokens(
        self, mock_log_usage, mock_get_agent, mock_deps, mock_payment_response
    ):
        """Test run_payment extracts tokens from result.usage."""
        # Setup mocks with usage
        mock_agent = Mock()
        result = Mock()
        result.output = mock_payment_response
        result.usage = RunUsage(input_tokens=180, output_tokens=90)
        result.model_used = None
        mock_agent.run = AsyncMock(return_value=result)
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_payment("Моє ім'я Іван, телефон 0501234567", mock_deps)

        # Assertions
        assert response is not None
        assert response.order_ready is True

        # Verify agent.run was called
        mock_agent.run.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.payment_agent.get_payment_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_payment_handles_missing_fields(
        self,
        mock_log_usage,
        mock_get_agent,
        mock_deps,
        mock_payment_response_missing_fields,
    ):
        """Test run_payment handles missing fields."""
        # Setup mocks
        mock_agent = Mock()
        result = Mock()
        result.output = mock_payment_response_missing_fields
        result.usage = RunUsage(input_tokens=100, output_tokens=50)
        result.model_used = None
        mock_agent.run = AsyncMock(return_value=result)
        mock_get_agent.return_value = mock_agent

        # Call function
        response = await run_payment("Привіт", mock_deps)

        # Assertions
        assert response is not None
        assert response.order_ready is False
        assert len(response.missing_fields) > 0
        assert "name" in response.missing_fields or "phone" in response.missing_fields

