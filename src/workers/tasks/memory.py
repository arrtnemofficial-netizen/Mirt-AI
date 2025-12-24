"""Memory maintenance background tasks.

These tasks handle:
- Time decay for memory facts
- Cleanup of expired memories
- Summary generation for active users
- Full maintenance cycle

Moved from src/services/domain/memory/memory_tasks.py to workers layer.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from src.services.domain.memory.memory_service import MemoryService
from src.services.domain.memory.memory_tasks import (
    generate_summaries_for_active_users,
    memory_maintenance,
)
from src.workers.sync_utils import run_sync

logger = logging.getLogger(__name__)

#
# NOTE ON API SHAPE (tests + backward compatibility)
# -----------------------------------------------
# Unit tests in `tests/unit/workers/test_memory_tasks.py` call:
#   task = apply_time_decay_task()
#   result = task.run()
#
# In Celery, the decorated function is a Task object; calling it would execute the task
# and return a dict. To match tests, we expose small factory functions that return the
# Task object, not execute it.
#

@shared_task(
    bind=True,
    name="src.workers.tasks.memory.apply_time_decay",
    soft_time_limit=300,
    time_limit=360,
)
def _apply_time_decay_task(self) -> dict[str, Any]:
    """Apply time decay to memory facts.

    Reduces importance of facts over time to prioritize recent information.

    Returns:
        Stats dict with affected counts
    """
    logger.info("[WORKER:MEMORY] Starting time decay task")
    service = MemoryService()
    if not service.enabled:
        return {"affected": 0, "error": "disabled"}

    affected = run_sync(service.apply_time_decay())
    return {"affected": int(affected), "elapsed_seconds": 0.0, "timestamp": ""}


def apply_time_decay_task():
    """Return Celery Task object (test-friendly)."""
    return _apply_time_decay_task


@shared_task(
    bind=True,
    name="src.workers.tasks.memory.cleanup_expired",
    soft_time_limit=300,
    time_limit=360,
)
def _cleanup_expired_task(self) -> dict[str, Any]:
    """Cleanup expired memory facts.

    Deactivates facts where expires_at < now() by setting is_active=False.

    Returns:
        Stats dict with cleaned counts
    """
    logger.info("[WORKER:MEMORY] Starting expired cleanup task")
    service = MemoryService()
    if not service.enabled:
        return {"cleaned": 0, "error": "disabled"}

    cleaned = run_sync(service.cleanup_expired())
    return {"cleaned": int(cleaned), "elapsed_seconds": 0.0, "timestamp": ""}


def cleanup_expired_task():
    """Return Celery Task object (test-friendly)."""
    return _cleanup_expired_task


@shared_task(
    bind=True,
    name="src.workers.tasks.memory.generate_summaries",
    soft_time_limit=600,
    time_limit=900,
)
def _generate_summaries_task(self, days: int = 7) -> dict[str, Any]:
    """Generate summaries for active users.

    Args:
        days: Consider users active if seen in last N days

    Returns:
        Stats dict with processed counts
    """
    logger.info("[WORKER:MEMORY] Starting summary generation for active users (last %d days)", days)
    return run_sync(generate_summaries_for_active_users(days))


def generate_summaries_task():
    """Return Celery Task object (test-friendly)."""
    return _generate_summaries_task


@shared_task(
    bind=True,
    name="src.workers.tasks.memory.memory_maintenance",
    soft_time_limit=900,
    time_limit=1200,
)
def _memory_maintenance_task(self) -> dict[str, Any]:
    """Full memory maintenance cycle.

    Runs:
    1. Time decay
    2. Cleanup expired
    3. Generate summaries

    Returns:
        Combined stats from all tasks
    """
    logger.info("[WORKER:MEMORY] Starting full memory maintenance cycle")
    return run_sync(memory_maintenance())


def memory_maintenance_task():
    """Return Celery Task object (test-friendly)."""
    return _memory_maintenance_task

