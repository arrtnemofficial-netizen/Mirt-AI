"""Summarization background tasks.

These tasks handle:
- Summarizing old conversations after SUMMARY_RETENTION_DAYS
- Saving summaries to mirt_users table
- Pruning old messages from mirt_messages
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from celery import shared_task

from src.conf.config import settings
from src.services.message_store import create_message_store
from src.services.summarization import (
    call_summarize_inactive_users,
    get_users_needing_summary,
    mark_user_summarized,
    run_retention,
)
# PostgreSQL only - no Supabase dependency
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

            # Remove ManyChat tags after successful summarization
            tag_removed = False
            human_needed_removed = False
            if manychat_subscriber_id:
                from src.integrations.manychat.api_client import get_manychat_client
                
                manychat_client = get_manychat_client()
                if manychat_client.is_configured:
                    try:
                        # Remove ai_responded tag
                        tag_removed = run_sync(_remove_manychat_tag(manychat_subscriber_id))
                        if tag_removed:
                            logger.info(
                                "[WORKER:SUMMARIZATION] Removed ai_responded tag for subscriber %s",
                                manychat_subscriber_id,
                            )
                        
                        # Remove humanNeeded-wd tag if present
                        async def _remove_human_tag():
                            return await manychat_client.remove_tag(manychat_subscriber_id, "humanNeeded-wd")
                        
                        human_needed_removed = run_sync(_remove_human_tag())
                        if human_needed_removed:
                            logger.info(
                                "[WORKER:SUMMARIZATION] Removed humanNeeded-wd tag for subscriber %s",
                                manychat_subscriber_id,
                            )
                    except Exception as e:
                        logger.warning(
                            "[WORKER:SUMMARIZATION] Failed to remove ManyChat tags: %s",
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

    # Use PostgreSQL
    try:
        import psycopg
        from psycopg.rows import dict_row
        from src.services.postgres_pool import get_postgres_url
        
        # Step 1: Call PostgreSQL function to mark inactive users
        try:
            postgres_url = get_postgres_url()
        except ValueError:
            logger.warning("[WORKER:SUMMARIZATION] PostgreSQL not configured, skipping")
            return {"status": "skipped", "reason": "no_postgres"}
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM summarize_inactive_users()")
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description] if cur.description else []
                marked_users = [dict(zip(columns, row)) for row in rows]
        
        logger.info(
            "[WORKER:SUMMARIZATION] Marked %d inactive users via PostgreSQL function",
            len(marked_users),
        )

        # Step 1.5: Check for users with humanNeeded-wd tag that need summarization (3+ days after escalation)
        from src.core.constants import DBTable
        from src.integrations.manychat.api_client import get_manychat_client
        
        manychat_client = get_manychat_client()
        escalation_users = []
        
        if manychat_client.is_configured:
            # Get users with last_interaction_at 3+ days ago from users table
            # For ManyChat, session_id = subscriber_id
            cutoff_date = (datetime.now(UTC) - timedelta(days=3)).isoformat()
            
            try:
                # Get inactive users from PostgreSQL users table
                with psycopg.connect(postgres_url) as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            f"""
                            SELECT user_id, last_interaction_at
                            FROM {DBTable.USERS}
                            WHERE last_interaction_at < %s
                            AND user_id IS NOT NULL
                            """,
                            (cutoff_date,),
                        )
                        inactive_users = cur.fetchall()
                
                if inactive_users:
                    # Get their session_ids from messages table
                    user_ids = [u.get("user_id") for u in inactive_users if u.get("user_id")]
                    
                    if user_ids:
                        # Get sessions for these users from PostgreSQL
                        with psycopg.connect(postgres_url) as conn:
                            with conn.cursor(row_factory=dict_row) as cur:
                                placeholders = ",".join(["%s"] * len(user_ids))
                                from src.core.constants import DBTable
                                cur.execute(
                                    f"""
                                    SELECT DISTINCT ON (user_id) session_id, user_id, created_at
                                    FROM {DBTable.MESSAGES}
                                    WHERE user_id IN ({placeholders})
                                    ORDER BY user_id, created_at DESC
                                    """,
                                    tuple(user_ids),
                                )
                                sessions_rows = cur.fetchall()
                        
                        # Group by user_id to get latest session
                        user_sessions: dict[str, str] = {}
                        for row in sessions_rows:
                            uid = row.get("user_id")
                            sid = row.get("session_id")
                            if uid and sid and uid not in user_sessions:
                                user_sessions[uid] = sid
                        
                        # Check which subscribers have humanNeeded-wd tag
                        async def _check_tag(subscriber_id: str) -> bool:
                            try:
                                subscriber = await manychat_client.get_subscriber_info(subscriber_id)
                                if subscriber:
                                    tags = subscriber.get("tags", [])
                                    # Tags can be list of strings or list of dicts
                                    if tags:
                                        tag_names = [
                                            tag if isinstance(tag, str) else tag.get("name", "")
                                            for tag in tags
                                        ]
                                        return "humanNeeded-wd" in tag_names
                                return False
                            except Exception:
                                return False
                        
                        # For ManyChat, session_id = subscriber_id
                        for user_id, session_id in user_sessions.items():
                            # Check if this session_id (subscriber_id) has humanNeeded-wd tag
                            has_tag = run_sync(_check_tag(session_id))
                            if has_tag:
                                escalation_users.append({
                                    "user_id": user_id,
                                    "session_id": session_id,
                                    "manychat_subscriber_id": session_id,  # session_id = subscriber_id for ManyChat
                                })
                        
                        if escalation_users:
                            logger.info(
                                "[WORKER:SUMMARIZATION] Found %d users with humanNeeded-wd tag needing summarization",
                                len(escalation_users),
                            )
            except Exception as e:
                logger.warning(
                    "[WORKER:SUMMARIZATION] Failed to check escalation users: %s",
                    e,
                )

        # Step 2: Get all users with 'needs_summary' tag
        users_to_summarize = get_users_needing_summary()
        
        # Add escalation users to the list
        for esc_user in escalation_users:
            if esc_user["user_id"] not in [u.get("user_id") for u in users_to_summarize]:
                users_to_summarize.append(esc_user)

        if not users_to_summarize:
            return {"status": "ok", "queued": 0, "marked": len(marked_users)}

        queued = 0
        for user in users_to_summarize:
            user_id = user.get("user_id")
            session_id = user.get("session_id")
            manychat_subscriber_id = user.get("manychat_subscriber_id")
            
            if user_id:
                # Queue summarization task for this user's session
                if session_id:
                    # Use session-specific summarization if we have session_id
                    summarize_session.delay(
                        session_id=session_id,
                        user_id=user_id,
                        manychat_subscriber_id=manychat_subscriber_id,
                    )
                else:
                    # Fallback to user history summarization
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
    user_id: int | str,
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

        # Get session for this user from PostgreSQL
        message_store = create_message_store()
        
        # Find user's session(s) using message_store
        messages = message_store.list_by_user(int(user_id) if isinstance(user_id, str) and user_id.isdigit() else user_id)
        
        if not messages:
            # No messages, just mark as summarized
            mark_user_summarized(user_id)
            return {"status": "skipped", "reason": "no_messages"}

        # Get first session_id from messages
        session_id = messages[0].session_id

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
