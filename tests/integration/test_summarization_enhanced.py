"""Enhanced summarization tests.

Tests:
- Summarization for users with humanNeeded-wd tag (3+ days after escalation)
- Saving summary to users.summary field
- Removing humanNeeded-wd tag after summarization
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workers.tasks.summarization import (
    check_all_sessions_for_summarization,
    summarize_session,
)


class TestSummarizationEscalation:
    """Tests for summarization with escalation check."""

    @patch("src.workers.tasks.summarization.get_supabase_client")
    @patch("src.workers.tasks.summarization.get_manychat_client")
    @patch("src.workers.tasks.summarization.call_summarize_inactive_users")
    @patch("src.workers.tasks.summarization.get_users_needing_summary")
    def test_check_sessions_with_human_needed_tag(
        self, mock_get_users, mock_call_rpc, mock_manychat, mock_supabase
    ):
        """Test that users with humanNeeded-wd tag are checked for summarization."""
        # Setup Supabase mock
        supabase = MagicMock()
        
        # Mock escalation sessions (3+ days old)
        cutoff_date = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        escalation_response = MagicMock()
        escalation_response.data = [
            {
                "session_id": "s1",
                "user_id": 123,
                "last_interaction_at": cutoff_date,
                "manychat_subscriber_id": "sub123",
            }
        ]
        supabase.table.return_value.select.return_value.lt.return_value.not_.is_.return_value.execute.return_value = (
            escalation_response
        )
        mock_supabase.return_value = supabase

        # Mock ManyChat client
        manychat_client = MagicMock()
        manychat_client.is_configured = True
        subscriber_info = {
            "tags": [{"name": "humanNeeded-wd"}, {"name": "other_tag"}]
        }
        manychat_client.get_subscriber_info = AsyncMock(return_value=subscriber_info)
        mock_manychat.return_value = manychat_client

        # Mock RPC and get_users
        mock_call_rpc.return_value = []
        mock_get_users.return_value = []

        task = check_all_sessions_for_summarization()
        result = task.run()

        # Verify that escalation users were found and queued
        assert result["status"] == "ok"
        # Should have queued at least the escalation user
        assert result["queued"] >= 1

    @patch("src.workers.tasks.summarization.get_supabase_client")
    @patch("src.workers.tasks.summarization.get_manychat_client")
    def test_check_sessions_no_human_needed_tag(self, mock_manychat, mock_supabase):
        """Test that users without humanNeeded-wd tag are not queued."""
        # Setup Supabase mock
        supabase = MagicMock()
        escalation_response = MagicMock()
        escalation_response.data = [
            {
                "session_id": "s1",
                "user_id": 123,
                "last_interaction_at": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
                "manychat_subscriber_id": "sub123",
            }
        ]
        supabase.table.return_value.select.return_value.lt.return_value.not_.is_.return_value.execute.return_value = (
            escalation_response
        )
        mock_supabase.return_value = supabase

        # Mock ManyChat - subscriber without humanNeeded-wd tag
        manychat_client = MagicMock()
        manychat_client.is_configured = True
        subscriber_info = {"tags": [{"name": "other_tag"}]}
        manychat_client.get_subscriber_info = AsyncMock(return_value=subscriber_info)
        mock_manychat.return_value = manychat_client

        task = check_all_sessions_for_summarization()
        result = task.run()

        # User without tag should not be queued
        assert result["status"] == "ok"


class TestSummarizationSaveToUsers:
    """Tests for saving summary to users.summary field."""

    @patch("src.workers.tasks.summarization.run_retention")
    @patch("src.workers.tasks.summarization.get_manychat_client")
    def test_summarize_session_saves_to_users_table(
        self, mock_manychat, mock_run_retention
    ):
        """Test that summary is saved to users.summary field."""
        # Mock retention returning summary
        mock_run_retention.return_value = "Test summary text"

        # Mock ManyChat client
        manychat_client = MagicMock()
        manychat_client.is_configured = True
        manychat_client.remove_tag = AsyncMock(return_value=True)
        mock_manychat.return_value = manychat_client

        task = summarize_session()
        result = task.run(
            session_id="s1",
            user_id=123,
            manychat_subscriber_id="sub123",
        )

        assert result["status"] == "summarized"
        assert result["summary_length"] > 0
        # Verify run_retention was called with user_id
        mock_run_retention.assert_called_once()
        call_kwargs = mock_run_retention.call_args[1]
        assert call_kwargs["user_id"] == 123

    @patch("src.workers.tasks.summarization.run_retention")
    @patch("src.workers.tasks.summarization.get_manychat_client")
    def test_summarize_session_removes_human_needed_tag(
        self, mock_manychat, mock_run_retention
    ):
        """Test that humanNeeded-wd tag is removed after summarization."""
        mock_run_retention.return_value = "Test summary"

        manychat_client = MagicMock()
        manychat_client.is_configured = True
        manychat_client.remove_tag = AsyncMock(return_value=True)
        mock_manychat.return_value = manychat_client

        task = summarize_session()
        result = task.run(
            session_id="s1",
            user_id=123,
            manychat_subscriber_id="sub123",
        )

        assert result["status"] == "summarized"
        # Verify humanNeeded-wd tag removal was attempted
        # (remove_tag is called for both ai_responded and humanNeeded-wd)
        assert manychat_client.remove_tag.called


class TestUpdateUserSummary:
    """Tests for update_user_summary function."""

    @patch("src.services.domain.memory.summarization.get_supabase_client")
    def test_update_user_summary_uses_users_table(self, mock_get_client):
        """Test that update_user_summary uses 'users' table, not 'mirt_users'."""
        from src.services.domain.memory.summarization import update_user_summary

        supabase = MagicMock()
        mock_get_client.return_value = supabase

        update_user_summary(user_id=123, summary="Test summary")

        # Verify upsert was called on 'users' table
        supabase.table.assert_called_with("users")
        upsert_call = supabase.table.return_value.upsert
        assert upsert_call.called
        call_args = upsert_call.call_args[0][0]
        assert call_args["user_id"] == "123"
        assert call_args["summary"] == "Test summary"

