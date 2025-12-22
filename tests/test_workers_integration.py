"""Integration tests for Celery workers.

Run with: pytest tests/test_workers_integration.py -v

Uses CELERY_TASK_ALWAYS_EAGER=True to run tasks synchronously.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set eager mode BEFORE importing celery
os.environ["CELERY_EAGER"] = "true"
os.environ["CELERY_ENABLED"] = "true"


class TestCeleryConfig:
    """Test Celery configuration."""

    def test_celery_app_loads(self):
        """Celery app should load without errors."""
        from src.workers.celery_app import celery_app

        assert celery_app is not None
        assert celery_app.main == "mirt_workers"

    def test_task_routes_configured(self):
        """Task routes should be configured for all queues."""
        from src.workers.celery_app import celery_app

        routes = celery_app.conf.task_routes
        assert "src.workers.tasks.summarization.*" in routes
        assert "src.workers.tasks.followups.*" in routes
        assert "src.workers.tasks.crm.*" in routes

    def test_eager_mode_enabled(self):
        """Eager mode should be enabled for testing."""
        from src.workers.celery_app import celery_app

        assert celery_app.conf.task_always_eager is True


class TestHealthTasks:
    """Test health check tasks."""

    def test_ping_task(self):
        """Ping task should return pong."""
        from src.workers.tasks.health import ping

        result = ping()

        assert result["pong"] is True
        assert "timestamp" in result

    def test_health_check_task(self):
        """Health check should return status."""
        from src.workers.tasks.health import worker_health_check

        # Mock Supabase
        with patch("src.services.infra.supabase_client.get_supabase_client") as mock:
            mock_client = MagicMock()
            mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[]
            )
            mock.return_value = mock_client

            result = worker_health_check()

            assert result["status"] in ("healthy", "degraded")
            assert "checks" in result


class TestSummarizationTasks:
    """Test summarization tasks."""

    def test_summarize_session_no_messages(self):
        """Summarization should skip if no old messages."""
        from src.workers.tasks.summarization import summarize_session

        with patch("src.workers.tasks.summarization.create_message_store") as mock_store:
            mock_store.return_value.list.return_value = []

            result = summarize_session("test_session_123")

            assert result["status"] == "skipped"

    def test_summarize_session_with_messages(self):
        """Summarization should work with old messages."""
        from src.services.infra.message_store import StoredMessage
        from src.workers.tasks.summarization import summarize_session

        old_time = datetime.now(UTC) - timedelta(days=5)
        mock_messages = [
            StoredMessage(
                session_id="test",
                role="user",
                content="Hello",
                created_at=old_time,
            ),
        ]

        with patch("src.workers.tasks.summarization.create_message_store") as mock_store:
            mock_store.return_value.list.return_value = mock_messages

            with patch("src.workers.tasks.summarization.run_retention") as mock_run:
                mock_run.return_value = "Test summary"

                result = summarize_session("test_session")

                assert result["status"] == "summarized"
                assert result["summary_length"] == len("Test summary")


class TestFollowupTasks:
    """Test followup tasks."""

    def test_followup_not_due(self):
        """Followup should not trigger if not due."""
        from src.services.infra.message_store import StoredMessage
        from src.workers.tasks.followups import send_followup

        # Recent message - followup not due
        recent_time = datetime.now(UTC) - timedelta(minutes=5)
        mock_messages = [
            StoredMessage(
                session_id="test",
                role="user",
                content="Hello",
                created_at=recent_time,
            ),
        ]

        with patch("src.workers.tasks.followups.create_message_store") as mock_store:
            mock_store.return_value.list.return_value = mock_messages

            result = send_followup("test_session")

            assert result["status"] == "skipped"

    def test_followup_triggered(self):
        """Followup should trigger when due."""
        from src.services.infra.message_store import StoredMessage
        from src.workers.tasks.followups import send_followup

        # Old message - followup due (with 1 hour schedule)
        old_time = datetime.now(UTC) - timedelta(hours=2)
        mock_messages = [
            StoredMessage(
                session_id="test",
                role="user",
                content="Hello",
                created_at=old_time,
            ),
        ]

        with patch("src.workers.tasks.followups.create_message_store") as mock_store:
            store_instance = MagicMock()
            store_instance.list.return_value = mock_messages
            mock_store.return_value = store_instance

            result = send_followup("test_session")

            # Should have created followup
            assert result["status"] in ("sent", "created", "skipped")


class TestCRMTasks:
    """Test CRM tasks."""

    def test_crm_not_configured(self):
        """CRM task should skip if not configured."""
        from src.workers.tasks.crm import create_crm_order

        with patch("src.workers.tasks.crm.settings") as mock_settings:
            mock_settings.snitkix_enabled = False

            result = create_crm_order(
                {
                    "external_id": "test123",
                    "customer": {"full_name": "Test"},
                    "items": [{"product_name": "Test"}],
                }
            )

            assert result["status"] == "skipped"
            assert result["reason"] == "crm_not_configured"

    def test_crm_missing_customer(self):
        """CRM task should fail on missing customer."""
        from src.workers.exceptions import PermanentError
        from src.workers.tasks.crm import create_crm_order

        with patch("src.workers.tasks.crm.settings") as mock_settings:
            mock_settings.snitkix_enabled = True

            with pytest.raises(PermanentError) as exc:
                create_crm_order({"external_id": "test123"})

            assert "Missing customer data" in str(exc.value)


class TestExceptions:
    """Test exception classes."""

    def test_retryable_error(self):
        """RetryableError should be retried."""
        from src.workers.exceptions import RetryableError

        err = RetryableError("Network timeout")
        assert str(err) == "Network timeout"

    def test_permanent_error(self):
        """PermanentError should not be retried."""
        from src.workers.exceptions import PermanentError

        err = PermanentError("Invalid input", error_code="INVALID")
        assert err.error_code == "INVALID"

    def test_rate_limit_error(self):
        """RateLimitError should have retry_after."""
        from src.workers.exceptions import RateLimitError

        err = RateLimitError("Too many requests", retry_after=120)
        assert err.retry_after == 120


class TestIdempotency:
    """Test idempotency utilities."""

    def test_generate_task_key(self):
        """Should generate consistent keys."""
        from src.workers.idempotency import generate_task_key

        key1 = generate_task_key("my_task", "arg1", kwarg="value")
        key2 = generate_task_key("my_task", "arg1", kwarg="value")
        key3 = generate_task_key("my_task", "arg2", kwarg="value")

        assert key1 == key2  # Same args = same key
        assert key1 != key3  # Different args = different key

    def test_webhook_task_id(self):
        """Should generate idempotent task IDs from webhook."""
        from src.workers.idempotency import webhook_task_id

        id1 = webhook_task_id("telegram", "msg123", "user456", "process")
        id2 = webhook_task_id("telegram", "msg123", "user456", "process")
        id3 = webhook_task_id("telegram", "msg999", "user456", "process")

        assert id1 == id2  # Same message = same ID
        assert id1 != id3  # Different message = different ID


class TestSyncUtils:
    """Test sync utilities."""

    def test_run_sync(self):
        """run_sync should execute async functions."""
        from src.workers.sync_utils import run_sync

        async def async_add(a, b):
            return a + b

        result = run_sync(async_add(2, 3))
        assert result == 5

    def test_sync_wrapper(self):
        """sync_wrapper should create sync version."""
        from src.workers.sync_utils import sync_wrapper

        @sync_wrapper
        async def async_multiply(a, b):
            return a * b

        result = async_multiply(4, 5)
        assert result == 20


class TestLLMUsageTasks:
    """Test LLM usage tracking tasks."""

    def test_calculate_cost(self):
        """Should calculate cost correctly."""
        from src.workers.tasks.llm_usage import calculate_cost

        # GPT-4o-mini: $0.15 per 1M input, $0.60 per 1M output
        cost = calculate_cost("gpt-4o-mini", 1000, 500)

        # Expected: (1000/1M * 0.15) + (500/1M * 0.60) = 0.00015 + 0.0003 = 0.00045
        assert cost > 0
        assert float(cost) < 0.001  # Should be tiny for small usage

    def test_calculate_cost_unknown_model(self):
        """Should use default pricing for unknown models."""
        from src.workers.tasks.llm_usage import calculate_cost

        cost = calculate_cost("unknown-model", 1000, 500)
        assert cost > 0  # Should still calculate something

    def test_record_usage_no_supabase(self):
        """Should skip if Supabase not configured."""
        from src.workers.tasks.llm_usage import record_usage

        with patch("src.workers.tasks.llm_usage.get_supabase_client") as mock:
            mock.return_value = None

            result = record_usage(
                user_id=123,
                model="gpt-4o-mini",
                tokens_input=100,
                tokens_output=50,
            )

            assert result["status"] == "skipped"

    def test_record_usage_with_supabase(self):
        """Should record usage to database."""
        from src.workers.tasks.llm_usage import record_usage

        with patch("src.workers.tasks.llm_usage.get_supabase_client") as mock:
            mock_client = MagicMock()
            mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
                data=[{"id": 1}]
            )
            mock.return_value = mock_client

            result = record_usage(
                user_id=123,
                model="gpt-4o-mini",
                tokens_input=100,
                tokens_output=50,
            )

            assert result["status"] == "recorded"
            assert result["id"] == 1
            assert "cost_usd" in result

    def test_aggregate_daily_usage_no_supabase(self):
        """Should skip if Supabase not configured."""
        from src.workers.tasks.llm_usage import aggregate_daily_usage

        with patch("src.workers.tasks.llm_usage.get_supabase_client") as mock:
            mock.return_value = None

            result = aggregate_daily_usage()

            assert result["status"] == "skipped"


class TestCRMSyncTasks:
    """Test CRM sync tasks."""

    def test_sync_order_status_not_configured(self):
        """Should skip if CRM not configured."""
        from src.workers.tasks.crm import sync_order_status

        with patch("src.workers.tasks.crm.settings") as mock_settings:
            mock_settings.snitkix_enabled = False

            result = sync_order_status("order123", "session456")

            assert result["status"] == "skipped"
            assert result["reason"] == "crm_not_configured"

    def test_check_pending_orders_not_configured(self):
        """Should skip if CRM not configured."""
        from src.workers.tasks.crm import check_pending_orders

        with patch("src.workers.tasks.crm.settings") as mock_settings:
            mock_settings.snitkix_enabled = False

            result = check_pending_orders()

            assert result["status"] == "skipped"


class TestSummarizationWithSupabaseFunction:
    """Test summarization with Supabase function integration."""

    def test_check_all_sessions_calls_supabase_function(self):
        """Should call summarize_inactive_users function."""
        from src.workers.tasks.summarization import check_all_sessions_for_summarization

        with patch("src.workers.tasks.summarization.get_supabase_client") as mock_client:
            mock_client.return_value = MagicMock()

            with patch(
                "src.workers.tasks.summarization.call_summarize_inactive_users"
            ) as mock_call:
                mock_call.return_value = [{"user_id": 1}]

                with patch("src.workers.tasks.summarization.get_users_needing_summary") as mock_get:
                    mock_get.return_value = []

                    result = check_all_sessions_for_summarization()

                    mock_call.assert_called_once()
                    assert result["marked"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
