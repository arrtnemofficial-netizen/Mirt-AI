"""Tests for memory maintenance tasks.

Tests the memory tasks moved to workers layer:
- apply_time_decay_task
- cleanup_expired_task
- generate_summaries_task
- memory_maintenance_task
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workers.tasks.memory import (
    apply_time_decay_task,
    cleanup_expired_task,
    generate_summaries_task,
    memory_maintenance_task,
)


@pytest.fixture
def mock_memory_service():
    """Mock MemoryService."""
    with patch("src.workers.tasks.memory.MemoryService") as mock:
        service = MagicMock()
        service.enabled = True
        service.apply_time_decay = AsyncMock(return_value=5)
        service.cleanup_expired = AsyncMock(return_value=3)
        mock.return_value = service
        yield service


@pytest.fixture
def mock_supabase():
    """Mock Supabase client."""
    with patch("src.services.domain.memory.memory_tasks.get_supabase_client") as mock:
        client = MagicMock()
        response = MagicMock()
        response.data = [
            {"user_id": "user1"},
            {"user_id": "user2"},
        ]
        client.table.return_value.select.return_value.gte.return_value.execute.return_value = (
            response
        )
        mock.return_value = client
        yield client


class TestApplyTimeDecayTask:
    """Tests for apply_time_decay_task."""

    def test_apply_time_decay_success(self, mock_memory_service):
        """Test successful time decay."""
        task = apply_time_decay_task()
        result = task.run()

        assert result["affected"] == 5
        assert "elapsed_seconds" in result
        assert "timestamp" in result
        mock_memory_service.apply_time_decay.assert_called_once()

    def test_apply_time_decay_disabled(self, mock_memory_service):
        """Test time decay when service is disabled."""
        mock_memory_service.enabled = False

        task = apply_time_decay_task()
        result = task.run()

        assert result["affected"] == 0
        assert result["error"] == "disabled"

    def test_apply_time_decay_error(self, mock_memory_service):
        """Test time decay error handling."""
        mock_memory_service.apply_time_decay.side_effect = Exception("Test error")

        task = apply_time_decay_task()
        with pytest.raises(Exception):
            task.run()


class TestCleanupExpiredTask:
    """Tests for cleanup_expired_task."""

    def test_cleanup_expired_success(self, mock_memory_service):
        """Test successful cleanup."""
        task = cleanup_expired_task()
        result = task.run()

        assert result["cleaned"] == 3
        assert "elapsed_seconds" in result
        mock_memory_service.cleanup_expired.assert_called_once()

    def test_cleanup_expired_disabled(self, mock_memory_service):
        """Test cleanup when service is disabled."""
        mock_memory_service.enabled = False

        task = cleanup_expired_task()
        result = task.run()

        assert result["cleaned"] == 0
        assert result["error"] == "disabled"


class TestGenerateSummariesTask:
    """Tests for generate_summaries_task."""

    @patch("src.services.domain.memory.memory_tasks.generate_user_summary")
    def test_generate_summaries_success(self, mock_generate, mock_supabase):
        """Test successful summary generation."""
        mock_generate.return_value = {"user_id": "user1", "summary_saved": True}

        task = generate_summaries_task()
        result = task.run(days=7)

        assert result["processed"] == 2
        assert result["successful"] == 2
        assert "elapsed_seconds" in result

    @patch("src.services.domain.memory.memory_tasks.get_supabase_client")
    def test_generate_summaries_no_client(self, mock_get_client):
        """Test summary generation when Supabase is not available."""
        mock_get_client.return_value = None

        task = generate_summaries_task()
        result = task.run(days=7)

        assert result["processed"] == 0
        assert result["error"] == "no_client"


class TestMemoryMaintenanceTask:
    """Tests for memory_maintenance_task."""

    @patch("src.services.domain.memory.memory_tasks.apply_time_decay")
    @patch("src.services.domain.memory.memory_tasks.cleanup_expired")
    @patch("src.services.domain.memory.memory_tasks.generate_summaries_for_active_users")
    def test_memory_maintenance_full_cycle(
        self, mock_summaries, mock_cleanup, mock_decay, mock_memory_service
    ):
        """Test full maintenance cycle."""
        mock_decay.return_value = {"affected": 5}
        mock_cleanup.return_value = {"cleaned": 3}
        mock_summaries.return_value = {"processed": 2, "successful": 2}

        task = memory_maintenance_task()
        result = task.run()

        assert "time_decay" in result
        assert "cleanup" in result
        assert "summaries" in result
        assert result["time_decay"]["affected"] == 5
        assert result["cleanup"]["cleaned"] == 3
        assert result["summaries"]["processed"] == 2
        assert "total_elapsed_seconds" in result

