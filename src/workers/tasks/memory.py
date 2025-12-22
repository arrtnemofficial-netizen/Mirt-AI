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

from src.services.domain.memory.memory_tasks import (
    apply_time_decay,
    cleanup_expired,
    generate_summaries_for_active_users,
    memory_maintenance,
)
from src.workers.exceptions import RetryableError
from src.workers.sync_utils import run_sync

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(RetryableError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.memory.apply_time_decay",
    soft_time_limit=300,
    time_limit=360,
)
def apply_time_decay_task(self) -> dict[str, Any]:
    """Apply time decay to memory facts.

    Reduces importance of facts over time to prioritize recent information.

    Returns:
        Stats dict with affected counts
    """
    logger.info("[WORKER:MEMORY] Starting time decay task")
    try:
        result = run_sync(apply_time_decay())
        logger.info("[WORKER:MEMORY] Time decay complete: %d facts affected", result.get("affected", 0))
        return result
    except Exception as e:
        logger.exception("[WORKER:MEMORY] Time decay failed: %s", e)
        raise RetryableError(f"Time decay failed: {e}") from e


@shared_task(
    bind=True,
    autoretry_for=(RetryableError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.memory.cleanup_expired",
    soft_time_limit=300,
    time_limit=360,
)
def cleanup_expired_task(self) -> dict[str, Any]:
    """Cleanup expired memory facts.

    Deactivates facts where expires_at < now() by setting is_active=False.

    Returns:
        Stats dict with cleaned counts
    """
    logger.info("[WORKER:MEMORY] Starting expired cleanup task")
    try:
        result = run_sync(cleanup_expired())
        logger.info("[WORKER:MEMORY] Cleanup complete: %d facts deactivated", result.get("cleaned", 0))
        return result
    except Exception as e:
        logger.exception("[WORKER:MEMORY] Cleanup failed: %s", e)
        raise RetryableError(f"Cleanup failed: {e}") from e


@shared_task(
    bind=True,
    autoretry_for=(RetryableError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.memory.generate_summaries",
    soft_time_limit=600,
    time_limit=900,
)
def generate_summaries_task(self, days: int = 7) -> dict[str, Any]:
    """Generate summaries for active users.

    Args:
        days: Consider users active if seen in last N days

    Returns:
        Stats dict with processed counts
    """
    logger.info("[WORKER:MEMORY] Starting summary generation for active users (last %d days)", days)
    try:
        result = run_sync(generate_summaries_for_active_users(days))
        logger.info(
            "[WORKER:MEMORY] Summary generation complete: %d/%d users",
            result.get("successful", 0),
            result.get("processed", 0),
        )
        return result
    except Exception as e:
        logger.exception("[WORKER:MEMORY] Summary generation failed: %s", e)
        raise RetryableError(f"Summary generation failed: {e}") from e


@shared_task(
    bind=True,
    autoretry_for=(RetryableError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.memory.memory_maintenance",
    soft_time_limit=900,
    time_limit=1200,
)
def memory_maintenance_task(self) -> dict[str, Any]:
    """Full memory maintenance cycle.

    Runs:
    1. Time decay
    2. Cleanup expired
    3. Generate summaries

    Returns:
        Combined stats from all tasks
    """
    logger.info("[WORKER:MEMORY] Starting full memory maintenance cycle")
    try:
        result = run_sync(memory_maintenance())
        logger.info(
            "[WORKER:MEMORY] Full maintenance complete in %.2fs",
            result.get("total_elapsed_seconds", 0),
        )
        return result
    except Exception as e:
        logger.exception("[WORKER:MEMORY] Memory maintenance failed: %s", e)
        raise RetryableError(f"Memory maintenance failed: {e}") from e

