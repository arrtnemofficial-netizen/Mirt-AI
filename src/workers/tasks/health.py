"""Health check tasks for worker monitoring."""

from __future__ import annotations

import logging
import platform
from datetime import UTC, datetime

from celery import shared_task

from src.core.constants import DBTable


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="src.workers.tasks.health.worker_health_check",
    soft_time_limit=10,
    time_limit=20,
)
def worker_health_check(self) -> dict:
    """Periodic health check task.

    This task runs every 5 minutes to verify:
    - Worker is alive and processing tasks
    - Can connect to Redis
    - Can connect to Supabase

    Returns:
        dict with health status
    """
    from src.services.infra.supabase_client import get_supabase_client

    health = {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "worker_id": self.request.hostname or "unknown",
        "task_id": self.request.id,
        "python_version": platform.python_version(),
        "checks": {},
    }

    # Check Redis (we're running, so it works)
    health["checks"]["redis"] = {"status": "ok"}

    # Check Supabase
    try:
        client = get_supabase_client()
        if client:
            # Simple query to verify connection
            client.table(DBTable.MESSAGES).select("id").limit(1).execute()
            health["checks"]["supabase"] = {"status": "ok"}
        else:
            health["checks"]["supabase"] = {"status": "not_configured"}
    except Exception as e:
        health["checks"]["supabase"] = {"status": "error", "error": str(e)}
        health["status"] = "degraded"

    # Log health status
    if health["status"] == "healthy":
        logger.info("[HEALTH] Worker healthy: %s", health["worker_id"])
    else:
        logger.warning("[HEALTH] Worker degraded: %s - %s", health["worker_id"], health["checks"])

    return health


@shared_task(
    bind=True,
    name="src.workers.tasks.health.ping",
    soft_time_limit=5,
    time_limit=10,
)
def ping(self) -> dict:
    """Simple ping task for testing worker connectivity.

    Returns:
        dict with pong response
    """
    return {
        "pong": True,
        "timestamp": datetime.now(UTC).isoformat(),
        "task_id": self.request.id,
        "worker_id": self.request.hostname or "unknown",
    }
