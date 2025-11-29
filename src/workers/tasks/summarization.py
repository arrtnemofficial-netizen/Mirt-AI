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
from src.services.summarization import (
    call_summarize_inactive_users,
    get_users_needing_summary,
    mark_user_summarized,
    run_retention,
)
from src.services.supabase_client import get_supabase_client
from src.workers.exceptions import DatabaseError, PermanentError, RetryableError
from src.workers.sync_utils import run_sync


logger = logging.getLogger(__name__)


async def _remove_manychat_tag(subscriber_id: str) -> bool:
    """Remove 'ai_responded' tag from ManyChat subscriber after summarization."""
    from src.integrations.manychat.api_client import remove_ai_tag_from_subscriber

    return await remove_ai_tag_from_subscriber(subscriber_id)


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
    manychat_subscriber_id: str | None = None,
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

            # Remove ManyChat tag after successful summarization
            tag_removed = False
            if manychat_subscriber_id:
                try:
                    tag_removed = run_sync(_remove_manychat_tag(manychat_subscriber_id))
                    if tag_removed:
                        logger.info(
                            "[WORKER:SUMMARIZATION] Removed ai_responded tag for subscriber %s",
                            manychat_subscriber_id,
                        )
                except Exception as e:
                    logger.warning(
                        "[WORKER:SUMMARIZATION] Failed to remove ManyChat tag: %s",
                        e,
                    )

            return {
                "status": "summarized",
                "session_id": session_id,
                "summary_length": len(summary),
                "manychat_tag_removed": tag_removed,
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
    Uses Supabase function summarize_inactive_users to find users
    inactive for 3+ days and queues summarization tasks.

    Returns:
        dict with count of queued tasks
    """
    logger.info("[WORKER:SUMMARIZATION] Starting periodic summarization check")

    client = get_supabase_client()
    if not client:
        logger.warning("[WORKER:SUMMARIZATION] Supabase not configured, skipping")
        return {"status": "skipped", "reason": "no_supabase"}

    try:
        # Step 1: Call Supabase function to mark inactive users
        marked_users = call_summarize_inactive_users()
        logger.info(
            "[WORKER:SUMMARIZATION] Marked %d inactive users via Supabase function",
            len(marked_users),
        )

        # Step 2: Get all users with 'needs_summary' tag
        users_to_summarize = get_users_needing_summary()

        if not users_to_summarize:
            return {"status": "ok", "queued": 0, "marked": len(marked_users)}

        queued = 0
        for user in users_to_summarize:
            user_id = user.get("user_id")
            if user_id:
                # Queue summarization task for this user's session
                summarize_user_history.delay(user_id)
                queued += 1

        logger.info(
            "[WORKER:SUMMARIZATION] Queued %d summarization tasks",
            queued,
        )
        return {
            "status": "ok",
            "queued": queued,
            "marked": len(marked_users),
        }

    except Exception as e:
        logger.exception("[WORKER:SUMMARIZATION] Error in periodic check: %s", e)
        return {"status": "error", "error": str(e)}


@shared_task(
    bind=True,
    autoretry_for=(RetryableError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.summarization.summarize_user_history",
    soft_time_limit=110,
    time_limit=120,
)
def summarize_user_history(
    self,
    user_id: int,
) -> dict:
    """Summarize all conversation history for a user.

    Uses Supabase function marking and handles full user history.

    Args:
        user_id: User ID to summarize

    Returns:
        dict with summarization result
    """
    logger.info(
        "[WORKER:SUMMARIZATION] Summarizing history for user=%s",
        user_id,
    )

    try:
        message_store = create_message_store()

        # Get session for this user
        client = get_supabase_client()
        if not client:
            return {"status": "skipped", "reason": "no_supabase"}

        # Find user's session(s)
        response = (
            client.table(settings.SUPABASE_MESSAGES_TABLE)
            .select("session_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if not response.data:
            # No messages, just mark as summarized
            mark_user_summarized(user_id)
            return {"status": "skipped", "reason": "no_messages"}

        session_id = response.data[0]["session_id"]

        # Run retention/summarization
        summary = run_retention(
            session_id=session_id,
            message_store=message_store,
            now=datetime.now(UTC),
            user_id=user_id,
        )

        # Mark user as summarized
        mark_user_summarized(user_id)

        if summary:
            logger.info(
                "[WORKER:SUMMARIZATION] User %s summarized, %d chars",
                user_id,
                len(summary),
            )
            return {
                "status": "summarized",
                "user_id": user_id,
                "summary_length": len(summary),
            }
        else:
            return {
                "status": "skipped",
                "user_id": user_id,
                "reason": "not_old_enough",
            }

    except PermanentError:
        raise
    except Exception as e:
        logger.exception(
            "[WORKER:SUMMARIZATION] Error summarizing user %s: %s",
            user_id,
            e,
        )
        raise DatabaseError(f"User summarization failed: {e}") from e
