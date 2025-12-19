"""
Unit tests for crm_error.py - CRM error handling node.

Tests cover:
1. _parse_user_intent - pure function for intent parsing
2. crm_error_node - main entry point with mocked dependencies
3. Error analysis and user choice handling
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.langgraph.nodes.crm_error import (
    _analyze_and_present_error,
    _handle_back_choice,
    _handle_escalate_choice,
    _handle_retry_choice,
    _parse_user_intent,
    _show_options_again,
    crm_error_node,
)


# =============================================================================
# _parse_user_intent Tests (Pure Function - No Mocking)
# =============================================================================


class TestParseUserIntent:
    """Tests for _parse_user_intent pure function."""

    @pytest.mark.parametrize(
        "message",
        [
            "повторити",
            "Повторити спробу",
            "retry",
            "RETRY",
            "знову спробувати",
            "спробувати ще раз",
        ],
    )
    def test_retry_intent_detected(self, message):
        """Detects retry keywords."""
        assert _parse_user_intent(message) == "retry"

    @pytest.mark.parametrize(
        "message",
        [
            "оператор",
            "Передай оператору",
            "escalate",
            "ESCALATE",
            "потрібна людина",
            "допомога",
        ],
    )
    def test_escalate_intent_detected(self, message):
        """Detects escalation keywords."""
        assert _parse_user_intent(message) == "escalate"

    @pytest.mark.parametrize(
        "message",
        [
            "назад",
            "Назад до замовлення",
            "back",
            "BACK",
            "повернутись",
        ],
    )
    def test_back_intent_detected(self, message):
        """Detects back keywords."""
        assert _parse_user_intent(message) == "back"

    @pytest.mark.parametrize(
        "message",
        [
            "що це",
            "не розумію",
            "hello",
            "",
        ],
    )
    def test_unknown_intent(self, message):
        """Unknown messages return 'unknown'."""
        assert _parse_user_intent(message) == "unknown"

    def test_empty_message(self):
        """Empty message returns 'unknown'."""
        assert _parse_user_intent("") == "unknown"

    def test_none_like_message(self):
        """None-like empty string returns 'unknown'."""
        assert _parse_user_intent("   ") == "unknown"


# =============================================================================
# crm_error_node Tests (Async - Mocked Dependencies)
# =============================================================================


class TestCrmErrorNode:
    """Tests for crm_error_node main entry."""

    @pytest.mark.asyncio
    async def test_first_entry_analyzes_error(self):
        """First entry (no awaiting_user_choice) analyzes error."""
        state = {
            "session_id": "sess_123",
            "crm_order_result": {"status": "failed", "error": "API timeout"},
            "crm_external_id": "ext_456",
            "crm_retry_count": 0,
        }

        mock_handler = MagicMock()
        mock_handler.handle_crm_failure = AsyncMock(
            return_value={
                "strategy": "retry",
                "can_retry": True,
                "message": "CRM помилка - спробуйте знову",
            }
        )

        with (
            patch(
                "src.agents.langgraph.nodes.crm_error.get_crm_error_handler",
                return_value=mock_handler,
            ),
            patch("src.agents.langgraph.nodes.crm_error.log_agent_step"),
        ):
            with patch("src.agents.langgraph.nodes.crm_error.track_metric"):
                result = await crm_error_node(state)

        assert result.goto == "crm_error"
        assert result.update["awaiting_user_choice"] is True
        assert "CRM помилка" in result.update["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_awaiting_choice_handles_user_input(self):
        """When awaiting_user_choice, processes user input."""
        state = {
            "session_id": "sess_123",
            "awaiting_user_choice": True,
            "messages": [{"role": "user", "content": "назад"}],
        }

        result = await crm_error_node(state)

        # "назад" should route to payment
        assert result.goto == "payment"


# =============================================================================
# _analyze_and_present_error Tests
# =============================================================================


class TestAnalyzeAndPresentError:
    """Tests for error analysis and presentation."""

    @pytest.mark.asyncio
    async def test_shows_retry_options_when_can_retry(self):
        """When can_retry=True, shows retry options."""
        state = {
            "crm_order_result": {"error": "timeout"},
            "crm_external_id": "ext_123",
            "crm_retry_count": 1,
        }

        mock_handler = MagicMock()
        mock_handler.handle_crm_failure = AsyncMock(
            return_value={
                "strategy": "retry",
                "can_retry": True,
                "message": "Тимчасова помилка",
            }
        )

        with (
            patch(
                "src.agents.langgraph.nodes.crm_error.get_crm_error_handler",
                return_value=mock_handler,
            ),
            patch("src.agents.langgraph.nodes.crm_error.log_agent_step"),
        ):
            with patch("src.agents.langgraph.nodes.crm_error.track_metric"):
                result = await _analyze_and_present_error(state, "sess_123")

        message = result.update["messages"][0]["content"]
        assert "повторити" in message
        assert "оператор" in message
        assert "назад" in message

    @pytest.mark.asyncio
    async def test_no_retry_options_when_cannot_retry(self):
        """When can_retry=False, doesn't show retry options."""
        state = {
            "crm_order_result": {"error": "critical"},
            "crm_external_id": "ext_123",
            "crm_retry_count": 5,
        }

        mock_handler = MagicMock()
        mock_handler.handle_crm_failure = AsyncMock(
            return_value={
                "strategy": "escalate",
                "can_retry": False,
                "message": "Критична помилка - передайте оператору",
            }
        )

        with (
            patch(
                "src.agents.langgraph.nodes.crm_error.get_crm_error_handler",
                return_value=mock_handler,
            ),
            patch("src.agents.langgraph.nodes.crm_error.log_agent_step"),
        ):
            with patch("src.agents.langgraph.nodes.crm_error.track_metric"):
                result = await _analyze_and_present_error(state, "sess_123")

        message = result.update["messages"][0]["content"]
        # Should NOT have retry options
        assert "Відповідаючи" not in message


# =============================================================================
# User Choice Handlers Tests
# =============================================================================


class TestHandleRetryChoice:
    """Tests for retry choice handling."""

    @pytest.mark.asyncio
    async def test_successful_retry_goes_to_upsell(self):
        """Successful retry routes to upsell."""
        state = {"step_number": 3}

        with patch(
            "src.agents.langgraph.nodes.crm_error.retry_crm_order_in_state",
            new_callable=AsyncMock,
            return_value={"crm_retry_result": {"success": True}},
        ):
            result = await _handle_retry_choice(state, "sess_123")

        assert result.goto == "upsell"
        assert "успішно" in result.update["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_failed_retry_stays_in_error(self):
        """Failed retry stays in crm_error."""
        state = {"step_number": 3}

        with patch(
            "src.agents.langgraph.nodes.crm_error.retry_crm_order_in_state",
            new_callable=AsyncMock,
            return_value={"crm_retry_result": {"success": False, "message": "Still failing"}},
        ):
            result = await _handle_retry_choice(state, "sess_123")

        assert result.goto == "crm_error"
        assert result.update["awaiting_user_choice"] is True


class TestHandleEscalateChoice:
    """Tests for escalation choice handling."""

    @pytest.mark.asyncio
    async def test_escalation_goes_to_end(self):
        """Escalation routes to end."""
        state = {
            "step_number": 3,
            "crm_external_id": "ext_123",
            "crm_error_result": {"message": "Error details"},
        }

        mock_handler = MagicMock()
        mock_handler.escalate_to_operator = AsyncMock(
            return_value={"message": "Передано оператору"}
        )

        with (
            patch(
                "src.agents.langgraph.nodes.crm_error.get_crm_error_handler",
                return_value=mock_handler,
            ),
            patch("src.agents.langgraph.nodes.crm_error.track_metric"),
        ):
            result = await _handle_escalate_choice(state, "sess_123")

        assert result.goto == "end"
        assert result.update["dialog_phase"] == "ESCALATED"


class TestHandleBackChoice:
    """Tests for back choice handling."""

    @pytest.mark.asyncio
    async def test_back_goes_to_payment(self):
        """Back choice routes to payment."""
        state = {"step_number": 3, "crm_order_result": {"old": "data"}}

        result = await _handle_back_choice(state, "sess_123")

        assert result.goto == "payment"
        assert result.update["dialog_phase"] == "OFFER_MADE"
        assert result.update["crm_order_result"] is None  # Cleared


class TestShowOptionsAgain:
    """Tests for showing options again."""

    @pytest.mark.asyncio
    async def test_shows_all_options(self):
        """Shows all available options."""
        state = {"step_number": 3}

        result = await _show_options_again(state, "sess_123")

        message = result.update["messages"][0]["content"]
        assert "повторити" in message
        assert "оператор" in message
        assert "назад" in message
        assert result.goto == "crm_error"
