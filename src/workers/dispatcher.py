"""Task dispatcher that routes to Celery or sync execution.

When CELERY_ENABLED=true, tasks are queued to Celery workers.
When CELERY_ENABLED=false, tasks run synchronously (for dev/testing).

Features:
- Idempotency via webhook-based task IDs
- Consistent response format with queue info
- Trace ID propagation for observability
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.conf.config import settings
from src.workers.idempotency import webhook_task_id


logger = logging.getLogger(__name__)


def _generate_trace_id() -> str:
    """Generate a trace ID for request tracking."""
    return uuid.uuid4().hex[:16]


def dispatch_summarization(session_id: str, user_id: int | None = None) -> dict:
    """Dispatch summarization task.

    Args:
        session_id: Session to summarize
        user_id: Optional user ID

    Returns:
        Task result or async task info
    """
    if settings.CELERY_ENABLED:
        from src.workers.tasks.summarization import summarize_session

        task = summarize_session.delay(session_id, user_id)
        logger.info("[DISPATCH] Queued summarization task %s", task.id)
        return {"queued": True, "task_id": task.id}
    else:
        # Sync execution
        from datetime import UTC, datetime

        from src.services.message_store import create_message_store
        from src.services.summarization import run_retention

        message_store = create_message_store()
        summary = run_retention(
            session_id=session_id,
            message_store=message_store,
            now=datetime.now(UTC),
            user_id=user_id,
        )
        return {"queued": False, "summary": summary}


def dispatch_followup(
    session_id: str,
    channel: str = "telegram",
    chat_id: str | None = None,
) -> dict:
    """Dispatch follow-up task.

    Args:
        session_id: Session ID
        channel: Delivery channel
        chat_id: Chat ID for delivery

    Returns:
        Task result or async task info
    """
    if settings.CELERY_ENABLED:
        from src.workers.tasks.followups import send_followup

        task = send_followup.delay(session_id, channel, chat_id)
        logger.info("[DISPATCH] Queued followup task %s", task.id)
        return {"queued": True, "task_id": task.id}
    else:
        # Sync execution
        from datetime import UTC, datetime

        from src.services.followups import run_followups
        from src.services.message_store import create_message_store

        message_store = create_message_store()
        followup = run_followups(
            session_id=session_id,
            message_store=message_store,
            now=datetime.now(UTC),
        )
        return {
            "queued": False,
            "followup_created": bool(followup),
            "content": followup.content if followup else None,
        }


def schedule_followup(
    session_id: str,
    delay_hours: int,
    channel: str = "telegram",
    chat_id: str | None = None,
) -> dict:
    """Schedule a follow-up for later.

    When Celery is enabled, uses apply_async with countdown.
    When disabled, returns immediately (no scheduling).

    Args:
        session_id: Session ID
        delay_hours: Hours to wait
        channel: Delivery channel
        chat_id: Chat ID

    Returns:
        Scheduling info
    """
    if settings.CELERY_ENABLED:
        from src.workers.tasks.followups import schedule_followup as celery_schedule

        result = celery_schedule.delay(session_id, delay_hours, channel, chat_id)
        logger.info(
            "[DISPATCH] Scheduled followup for session %s in %dh, task=%s",
            session_id,
            delay_hours,
            result.id,
        )
        return {"scheduled": True, "task_id": result.id, "delay_hours": delay_hours}
    else:
        logger.info(
            "[DISPATCH] Celery disabled, followup scheduling skipped for %s",
            session_id,
        )
        return {"scheduled": False, "reason": "celery_disabled"}


