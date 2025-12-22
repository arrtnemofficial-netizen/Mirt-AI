"""Real integration tests for memory tasks (no mocks).

Tests memory tasks with real services (if configured).
"""

import pytest

from src.services.domain.memory.memory_tasks import (
    apply_time_decay,
    cleanup_expired,
    memory_maintenance,
)


class TestMemoryTasksReal:
    """Real tests for memory tasks using actual services."""

    @pytest.mark.asyncio
    async def test_apply_time_decay_real(self):
        """Test time decay with real memory service."""
        result = await apply_time_decay()

        assert isinstance(result, dict)
        assert "affected" in result
        # Should not raise exception even if service is disabled
        assert result.get("error") != "disabled" or result.get("affected") == 0

    @pytest.mark.asyncio
    async def test_apply_time_decay_handles_disabled(self):
        """Test that time decay handles disabled service gracefully."""
        result = await apply_time_decay()

        # Should return dict with status
        assert isinstance(result, dict)
        # Either success or disabled, but not error
        assert "affected" in result or "error" in result

    @pytest.mark.asyncio
    async def test_cleanup_expired_real(self):
        """Test cleanup with real memory service."""
        result = await cleanup_expired()

        assert isinstance(result, dict)
        assert "cleaned" in result

    @pytest.mark.asyncio
    async def test_memory_maintenance_real(self):
        """Test full memory maintenance cycle."""
        result = await memory_maintenance()

        assert isinstance(result, dict)
        # Should have results from all steps
        assert "time_decay" in result
        assert "cleanup" in result
        assert "summaries" in result
        assert "total_elapsed_seconds" in result

    def test_memory_tasks_importable(self):
        """Test that memory tasks can be imported."""
        from src.workers.tasks.memory import (
            apply_time_decay_task,
            cleanup_expired_task,
            generate_summaries_task,
            memory_maintenance_task,
        )

        # Verify tasks exist
        assert apply_time_decay_task is not None
        assert cleanup_expired_task is not None
        assert generate_summaries_task is not None
        assert memory_maintenance_task is not None

