"""Tests for CRM dispatcher functions.

Tests:
- dispatch_crm_order_status
- Integration with dispatcher pattern
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workers.dispatcher import dispatch_crm_order_status


class TestDispatchCrmOrderStatus:
    """Tests for dispatch_crm_order_status."""

    @patch("src.workers.dispatcher.settings")
    def test_dispatch_with_celery_enabled(self, mock_settings):
        """Test dispatch when Celery is enabled."""
        mock_settings.CELERY_ENABLED = True

        # Mock the task
        mock_task = MagicMock()
        task_result = MagicMock()
        task_result.id = "task123"
        mock_task.delay.return_value = task_result
        
        with patch("src.workers.dispatcher.sync_order_status", mock_task):
            result = dispatch_crm_order_status(
                order_id="order123",
                session_id="session123",
                new_status="completed",
            )

            assert result["queued"] is True
            assert result["task_id"] == "task123"
            mock_task.delay.assert_called_once_with(
                "order123", "session123", "completed"
            )

    @patch("src.workers.dispatcher.settings")
    @patch("src.workers.dispatcher.get_snitkix_client")
    @patch("src.workers.dispatcher.get_supabase_client")
    @patch("src.workers.dispatcher.run_sync")
    def test_dispatch_sync_mode(self, mock_run_sync, mock_supabase, mock_snitkix, mock_settings):
        """Test dispatch in sync mode (Celery disabled)."""
        mock_settings.CELERY_ENABLED = False
        mock_settings.snitkix_enabled = True

        # Mock Snitkix client
        snitkix_client = MagicMock()
        order_status = MagicMock()
        order_status.status = "completed"
        snitkix_client.get_order_status = AsyncMock(return_value=order_status)
        mock_snitkix.return_value = snitkix_client

        # Mock Supabase client
        supabase = MagicMock()
        mock_supabase.return_value = supabase

        # Mock run_sync to execute the async function
        mock_run_sync.side_effect = lambda coro: {
            "status": "synced",
            "order_id": "order123",
            "order_status": "completed",
            "session_id": "session123",
        }

        result = dispatch_crm_order_status(
            order_id="order123",
            session_id="session123",
            new_status=None,  # Will fetch from CRM
        )

        assert result["queued"] is False
        assert "status" in result

    @patch("src.workers.dispatcher.settings")
    def test_dispatch_crm_not_configured(self, mock_settings):
        """Test dispatch when CRM is not configured."""
        mock_settings.CELERY_ENABLED = False
        mock_settings.snitkix_enabled = False

        result = dispatch_crm_order_status(
            order_id="order123",
            session_id="session123",
            new_status="completed",
        )

        assert result["queued"] is False
        assert result["status"] == "crm_not_configured"

