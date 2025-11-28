"""Summarization background tasks.

These tasks handle:
- Summarizing old conversations after SUMMARY_RETENTION_DAYS
- Saving summaries to mirt_users table
- Pruning old messages from mirt_messages
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from celery import shared_task

from src.conf.config import settings
from src.services.message_store import create_message_store
from src.services.summarization import run_retention
from src.services.supabase_client import get_supabase_client
from src.workers.exceptions import DatabaseError, PermanentError, RetryableError


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(RetryableError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.summarization.summarize_session",
    soft_time_limit=110,
    time_limit=120,
)
def summarize_session(
    self,
    session_id: str,
    user_id: int | None = None,
) -> dict:
    """Summarize a single session and prune old messages.

    Args:
        session_id: The session ID to summarize
        user_id: Optional user ID for saving summary

    Returns:
        dict with status and summary text
    """
    logger.info(
        "[WORKER:SUMMARIZATION] Starting summarization for session=%s user=%s",
        session_id,
        user_id,
    )

    try:
        message_store = create_message_store()
        summary = run_retention(
            session_id=session_id,
            message_store=message_store,
            now=datetime.now(UTC),
            user_id=user_id,
        )

        if summary:
            logger.info(
                "[WORKER:SUMMARIZATION] Session %s summarized, %d chars",
                session_id,
                len(summary),
            )
            return {
                "status": "summarized",
                "session_id": session_id,
                "summary_length": len(summary),
            }
        else:
            logger.info(
                "[WORKER:SUMMARIZATION] Session %s not ready for summarization",
                session_id,
            )
            return {
                "status": "skipped",
                "session_id": session_id,
                "reason": "not_old_enough",
            }

    except PermanentError:
        raise  # Don't retry
    except Exception as e:
        logger.exception(
            "[WORKER:SUMMARIZATION] Error summarizing session %s: %s",
            session_id,
            e,
        )
        raise DatabaseError(f"Summarization failed: {e}") from e


@shared_task(
    bind=True,
    name="src.workers.tasks.summarization.check_all_sessions_for_summarization",
)
def check_all_sessions_for_summarization(self) -> dict:
    """Check all sessions and queue summarization tasks for eligible ones.

    This is a periodic task that runs via Celery Beat.
    It finds sessions that haven't been active for SUMMARY_RETENTION_DAYS
    and queues individual summarization tasks.

    Returns:
        dict with count of queued tasks
    """
    logger.info("[WORKER:SUMMARIZATION] Starting periodic summarization check")

    client = get_supabase_client()
    if not client:
        logger.warning("[WORKER:SUMMARIZATION] Supabase not configured, skipping")
        return {"status": "skipped", "reason": "no_supabase"}

    try:
        # Get distinct session IDs from mirt_messages
        response = client.table(settings.SUPABASE_MESSAGES_TABLE).select("session_id").execute()

        if not response.data:
            return {"status": "ok", "queued": 0}

        # Get unique session IDs
        session_ids = list({row["session_id"] for row in response.data})
        queued = 0

        for session_id in session_ids:
            # Queue individual summarization task
            summarize_session.delay(session_id)
            queued += 1

        logger.info(
            "[WORKER:SUMMARIZATION] Queued %d summarization tasks",
            queued,
        )
        return {"status": "ok", "queued": queued}

    except Exception as e:
        logger.exception("[WORKER:SUMMARIZATION] Error in periodic check: %s", e)
        return {"status": "error", "error": str(e)}
