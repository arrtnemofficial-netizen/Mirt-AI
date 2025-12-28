"""Memory maintenance Celery tasks.

These tasks handle:
- Cleanup expired memories (mirt_memories with expires_at < now)
- Time decay for old memories
"""

from __future__ import annotations

import logging

from celery import shared_task

from src.services.memory.tasks import cleanup_expired
from src.workers.exceptions import DatabaseError, PermanentError, RetryableError
from src.workers.sync_utils import run_sync


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="src.workers.tasks.memory.cleanup_expired_memories",
    soft_time_limit=300,  # 5 minutes
    time_limit=360,  # 6 minutes
    queue="default",
)
def cleanup_expired_memories(self) -> dict:
    """Cleanup expired memories (Celery task wrapper).
    
    Deactivates memories with expires_at < now().
    This task should run daily via Celery Beat.
    
    Returns:
        dict with cleaned count and status
    """
    logger.info("[WORKER:MEMORY] Starting expired memories cleanup...")
    
    try:
        result = run_sync(cleanup_expired())
        
        if result.get("error"):
            logger.error(
                "[WORKER:MEMORY] Cleanup failed: %s",
                result.get("error"),
            )
            return result
        
        cleaned = result.get("cleaned", 0)
        logger.info(
            "[WORKER:MEMORY] Cleanup complete: %d expired memories deactivated",
            cleaned,
        )
        
        return result
    except Exception as e:
        logger.exception("[WORKER:MEMORY] Error in cleanup_expired_memories: %s", e)
        raise DatabaseError(f"Memory cleanup failed: {e}") from e

