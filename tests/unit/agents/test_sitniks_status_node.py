"""Tests for Sitniks status update node.

Tests the LangGraph node that automatically updates Sitniks CRM statuses.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.langgraph.nodes.sitniks_status import update_sitniks_status


class TestSitniksStatusNode:
    """Tests for update_sitniks_status node."""

    @patch("src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service")
    def test_update_status_first_touch(self, mock_get_service):
        """Test first_touch stage handling."""
        service = MagicMock()
        service.enabled = True
        service.handle_first_touch = AsyncMock(
            return_value={"success": True, "chat_id": "chat123"}
        )
        mock_get_service.return_value = service

        state = {
            "session_id": "s1",
            "user_id": "user123",
            "metadata": {
                "stage": "first_touch",
                "instagram_username": "test_user",
            },
            "step_number": 1,
        }

        result = update_sitniks_status(state)

        assert result["step_number"] == 2
        service.handle_first_touch.assert_called_once_with(
            user_id="user123",
            instagram_username="test_user",
            telegram_username=None,
        )

    @patch("src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service")
    def test_update_status_give_requisites(self, mock_get_service):
        """Test give_requisites stage handling."""
        service = MagicMock()
        service.enabled = True
        service.handle_invoice_sent = AsyncMock(return_value=True)
        mock_get_service.return_value = service

        state = {
            "session_id": "s1",
            "user_id": "user123",
            "metadata": {"stage": "give_requisites"},
            "step_number": 1,
        }

        result = update_sitniks_status(state)

        assert result["step_number"] == 2
        service.handle_invoice_sent.assert_called_once_with("user123")

    @patch("src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service")
    def test_update_status_escalation(self, mock_get_service):
        """Test escalation stage handling."""
        service = MagicMock()
        service.enabled = True
        service.handle_escalation = AsyncMock(
            return_value={"success": True, "status_set": True}
        )
        mock_get_service.return_value = service

        state = {
            "session_id": "s1",
            "user_id": "user123",
            "metadata": {"stage": "escalation"},
            "step_number": 1,
        }

        result = update_sitniks_status(state)

        assert result["step_number"] == 2
        service.handle_escalation.assert_called_once_with("user123")

    @patch("src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service")
    def test_update_status_no_stage(self, mock_get_service):
        """Test that node passes through when no stage is set."""
        state = {
            "session_id": "s1",
            "user_id": "user123",
            "metadata": {},
            "step_number": 1,
        }

        result = update_sitniks_status(state)

        assert result["step_number"] == 2
        # Service should not be called
        mock_get_service.assert_not_called()

    @patch("src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service")
    def test_update_status_service_disabled(self, mock_get_service):
        """Test that node passes through when service is disabled."""
        service = MagicMock()
        service.enabled = False
        mock_get_service.return_value = service

        state = {
            "session_id": "s1",
            "user_id": "user123",
            "metadata": {"stage": "first_touch"},
            "step_number": 1,
        }

        result = update_sitniks_status(state)

        assert result["step_number"] == 2
        # Service methods should not be called
        assert not hasattr(service, "handle_first_touch") or not service.handle_first_touch.called

    @patch("src.agents.langgraph.nodes.sitniks_status.get_sitniks_chat_service")
    def test_update_status_error_handling(self, mock_get_service):
        """Test that errors don't break the graph."""
        service = MagicMock()
        service.enabled = True
        service.handle_first_touch = AsyncMock(side_effect=Exception("API error"))
        mock_get_service.return_value = service

        state = {
            "session_id": "s1",
            "user_id": "user123",
            "metadata": {"stage": "first_touch"},
            "step_number": 1,
        }

        # Should not raise exception
        result = update_sitniks_status(state)

        assert result["step_number"] == 2

