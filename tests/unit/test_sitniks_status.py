"""
Unit tests for sitniks_status.py - CRM status integration node.

Tests cover:
1. determine_stage - pure function that detects stage from state
2. sitniks_status_node - async node with mocked service
3. sitniks_pre_response_node - first touch handling
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.langgraph.nodes.sitniks_status import (
    STAGE_ESCALATION,
    STAGE_FIRST_TOUCH,
    STAGE_GIVE_REQUISITES,
    determine_stage,
    sitniks_pre_response_node,
    sitniks_status_node,
)
from src.core.state_machine import State


# =============================================================================
# determine_stage Tests (Pure Function - No Mocking Needed)
# =============================================================================


class TestDetermineStage:
    """Tests for determine_stage pure function."""

    def test_first_message_returns_first_touch(self):
        """First message triggers first_touch stage."""
        state = {"is_first_message": True}
        assert determine_stage(state) == STAGE_FIRST_TOUCH

    def test_step_one_returns_first_touch(self):
        """Step number 1 triggers first_touch stage."""
        state = {"step_number": 1}
        assert determine_stage(state) == STAGE_FIRST_TOUCH

    def test_escalation_in_agent_response(self):
        """Escalation in agent_response triggers escalation stage."""
        state = {"step_number": 5, "agent_response": {"escalation": {"reason": "USER_REQUEST"}}}
        assert determine_stage(state) == STAGE_ESCALATION

    def test_escalation_level_in_metadata(self):
        """Escalation level in metadata triggers escalation stage."""
        state = {"step_number": 5, "agent_response": {"metadata": {"escalation_level": "URGENT"}}}
        assert determine_stage(state) == STAGE_ESCALATION

    def test_payment_state_show_payment_phase(self):
        """STATE_5 + SHOW_PAYMENT triggers give_requisites."""
        state = {
            "step_number": 5,
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "dialog_phase": "SHOW_PAYMENT",
        }
        assert determine_stage(state) == STAGE_GIVE_REQUISITES

    def test_payment_state_waiting_for_proof(self):
        """STATE_5 + WAITING_FOR_PAYMENT_PROOF triggers give_requisites."""
        state = {
            "step_number": 5,
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
        }
        assert determine_stage(state) == STAGE_GIVE_REQUISITES

    def test_iban_in_message_triggers_requisites(self):
        """IBAN in message content triggers give_requisites."""
        state = {
            "step_number": 5,
            "current_state": State.STATE_3_SIZE_COLOR.value,  # Not payment state
            "messages": [{"role": "assistant", "content": "Реквізити: IBAN UA1234567890"}],
        }
        assert determine_stage(state) == STAGE_GIVE_REQUISITES

    def test_no_stage_for_regular_conversation(self):
        """Regular conversation step returns None."""
        state = {
            "step_number": 5,
            "current_state": State.STATE_3_SIZE_COLOR.value,
            "dialog_phase": "WAITING_FOR_SIZE",
        }
        assert determine_stage(state) is None

    def test_escalation_level_none_is_ignored(self):
        """Escalation level 'NONE' is treated as no escalation."""
        state = {"step_number": 5, "agent_response": {"metadata": {"escalation_level": "NONE"}}}
        assert determine_stage(state) is None

    def test_escalation_level_empty_is_ignored(self):
        """Empty escalation level is treated as no escalation."""
        state = {"step_number": 5, "agent_response": {"metadata": {"escalation_level": ""}}}
        assert determine_stage(state) is None


# =============================================================================
# sitniks_status_node Tests (Async - Mocked Service)
# =============================================================================


class TestSitniksStatusNode:
    """Tests for sitniks_status_node async function."""

    @pytest.mark.asyncio
    async def test_no_stage_skips_update(self):
        """When no stage detected, returns without API call."""
        state = {
            "step_number": 5,
            "current_state": State.STATE_3_SIZE_COLOR.value,
        }

        result = await sitniks_status_node(state)

        assert result.update["sitniks_status_updated"] is False
        assert result.goto == "__end__"

    @pytest.mark.asyncio
    async def test_service_not_enabled(self):
        """When service disabled, returns with error message."""
        state = {"is_first_message": True}

        mock_service = MagicMock()
        mock_service.enabled = False

        with patch(
            "src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service",
            return_value=mock_service,
        ):
            result = await sitniks_status_node(state)

        assert result.update["sitniks_status_updated"] is False
        assert result.update["sitniks_stage"] == STAGE_FIRST_TOUCH
        assert "not configured" in result.update.get("sitniks_error", "")

    @pytest.mark.asyncio
    async def test_first_touch_calls_service(self):
        """First touch stage calls handle_first_touch."""
        state = {
            "is_first_message": True,
            "session_id": "sess_123",
            "metadata": {
                "instagram_username": "test_user",
            },
        }

        mock_service = MagicMock()
        mock_service.enabled = True
        mock_service.handle_first_touch = AsyncMock(
            return_value={"success": True, "chat_id": "chat_456"}
        )

        with patch(
            "src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service",
            return_value=mock_service,
        ):
            result = await sitniks_status_node(state)

        mock_service.handle_first_touch.assert_called_once_with(
            user_id="sess_123",
            instagram_username="test_user",
            telegram_username=None,
        )
        assert result.update["sitniks_status_updated"] is True
        assert result.update["sitniks_chat_id"] == "chat_456"

    @pytest.mark.asyncio
    async def test_give_requisites_calls_service(self):
        """Give requisites stage calls handle_invoice_sent."""
        state = {
            "step_number": 5,
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "dialog_phase": "SHOW_PAYMENT",
            "session_id": "sess_123",
        }

        mock_service = MagicMock()
        mock_service.enabled = True
        mock_service.handle_invoice_sent = AsyncMock(return_value=True)

        with patch(
            "src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service",
            return_value=mock_service,
        ):
            result = await sitniks_status_node(state)

        mock_service.handle_invoice_sent.assert_called_once_with("sess_123")
        assert result.update["sitniks_status_updated"] is True
        assert result.update["sitniks_stage"] == STAGE_GIVE_REQUISITES

    @pytest.mark.asyncio
    async def test_escalation_calls_service(self):
        """Escalation stage calls handle_escalation."""
        state = {
            "step_number": 5,
            "agent_response": {"escalation": {"reason": "USER_REQUEST"}},
            "session_id": "sess_123",
        }

        mock_service = MagicMock()
        mock_service.enabled = True
        mock_service.handle_escalation = AsyncMock(
            return_value={"success": True, "manager_assigned": "Олена"}
        )

        with patch(
            "src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service",
            return_value=mock_service,
        ):
            result = await sitniks_status_node(state)

        mock_service.handle_escalation.assert_called_once_with("sess_123")
        assert result.update["sitniks_stage"] == STAGE_ESCALATION

    @pytest.mark.asyncio
    async def test_service_exception_handled(self):
        """Exceptions from service are caught and logged."""
        state = {
            "is_first_message": True,
            "session_id": "sess_123",
        }

        mock_service = MagicMock()
        mock_service.enabled = True
        mock_service.handle_first_touch = AsyncMock(side_effect=Exception("API Error"))

        with patch(
            "src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service",
            return_value=mock_service,
        ):
            result = await sitniks_status_node(state)

        # Should not raise, but log error
        assert result.update["sitniks_status_updated"] is False
        assert "API Error" in str(result.update.get("sitniks_result", {}).get("error", ""))


# =============================================================================
# sitniks_pre_response_node Tests
# =============================================================================


class TestSitniksPreResponseNode:
    """Tests for sitniks_pre_response_node async function."""

    @pytest.mark.asyncio
    async def test_skips_after_first_step(self):
        """Skips processing after step 1."""
        state = {"step_number": 5}

        result = await sitniks_pre_response_node(state)

        assert result.get("sitniks_first_touch_done") is False

    @pytest.mark.asyncio
    async def test_skips_if_already_done(self):
        """Skips if already processed."""
        state = {
            "step_number": 1,
            "sitniks_first_touch_done": True,
        }

        result = await sitniks_pre_response_node(state)

        assert result == {}

    @pytest.mark.asyncio
    async def test_no_username_available(self):
        """Handles case when no username available."""
        state = {
            "step_number": 1,
            "metadata": {},
        }

        result = await sitniks_pre_response_node(state)

        assert result.get("sitniks_first_touch_done") is True
        assert result.get("sitniks_no_username") is True

    @pytest.mark.asyncio
    async def test_service_not_enabled(self):
        """Returns early when service not enabled."""
        state = {
            "step_number": 1,
            "metadata": {"instagram_username": "test"},
        }

        mock_service = MagicMock()
        mock_service.enabled = False

        with patch(
            "src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service",
            return_value=mock_service,
        ):
            result = await sitniks_pre_response_node(state)

        assert result.get("sitniks_first_touch_done") is True
        assert result.get("sitniks_not_enabled") is True

    @pytest.mark.asyncio
    async def test_successful_first_touch(self):
        """Successful first touch processing."""
        state = {
            "step_number": 1,
            "session_id": "sess_123",
            "metadata": {"user_nickname": "telegram_user"},
        }

        mock_service = MagicMock()
        mock_service.enabled = True
        mock_service.handle_first_touch = AsyncMock(
            return_value={"success": True, "chat_id": "chat_789"}
        )

        with patch(
            "src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service",
            return_value=mock_service,
        ):
            result = await sitniks_pre_response_node(state)

        assert result.get("sitniks_first_touch_done") is True
        assert result.get("sitniks_chat_id") == "chat_789"

    @pytest.mark.asyncio
    async def test_exception_handled(self):
        """Exceptions are caught and returned as error."""
        state = {
            "step_number": 1,
            "session_id": "sess_123",
            "metadata": {"instagram_username": "test"},
        }

        mock_service = MagicMock()
        mock_service.enabled = True
        mock_service.handle_first_touch = AsyncMock(side_effect=Exception("Connection Error"))

        with patch(
            "src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service",
            return_value=mock_service,
        ):
            result = await sitniks_pre_response_node(state)

        assert result.get("sitniks_first_touch_done") is True
        assert "Connection Error" in result.get("sitniks_first_touch_error", "")
