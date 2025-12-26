"""Summarization service for conversation history.

Handles:
- Summarizing old conversations after SUMMARY_RETENTION_DAYS
- Saving summaries to users table
- Pruning old messages from messages table
- Integration with PostgreSQL function summarize_inactive_users
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore

from src.conf.config import settings
from src.core.constants import DBTable, MessageTag
from src.services.storage import MessageStore, StoredMessage
from src.services.storage import get_postgres_url


logger = logging.getLogger(__name__)


def _older_than_cutoff(messages: list[StoredMessage], now: datetime) -> bool:
    if not messages:
        return False
    last = messages[-1].created_at
    return now - last >= timedelta(days=settings.SUMMARY_RETENTION_DAYS)


def _drop_human_tag(messages: list[StoredMessage]) -> list[StoredMessage]:
    cleaned: list[StoredMessage] = []
    for msg in messages:
        if MessageTag.HUMAN_NEEDED in msg.tags:
            msg = StoredMessage(
                session_id=msg.session_id,
                role=msg.role,
                content=msg.content,
                created_at=msg.created_at,
                tags=[t for t in msg.tags if t != MessageTag.HUMAN_NEEDED],
            )
        cleaned.append(msg)
    return cleaned


def summarise_messages(messages: list[StoredMessage]) -> str:
    parts = []
    for msg in messages:
        prefix = "Користувач" if msg.role == "user" else "Асистент"
        parts.append(f"{prefix}: {msg.content}")
    return " \n".join(parts)


def update_user_summary(user_id: int, summary: str) -> None:
    """Update summary field in users table."""
    if psycopg is None:
        logger.error("psycopg not installed")
        return

    try:
        url = get_postgres_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {DBTable.USERS} (user_id, summary, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (user_id)
                    DO UPDATE SET summary = EXCLUDED.summary, updated_at = NOW()
                    """,
                    (str(user_id), summary),
                )
                conn.commit()
    except Exception as e:
        logger.error("Failed to update summary for user %s: %s", user_id, e)


def call_summarize_inactive_users() -> list[dict[str, Any]]:
    """Call PostgreSQL function summarize_inactive_users.

    This function marks users as needing summary after 3 days of inactivity.
    It's called by the periodic summarization task.

    The PostgreSQL function:
    - Finds users where last_interaction_at < NOW() - INTERVAL '3 days'
    - Excludes already summarized users
    - Adds 'needs_summary' tag
    - Returns list of affected users

    Returns:
        List of users marked for summarization with fields:
        - user_id
        - username
        - last_interaction_at
    """
    if psycopg is None:
        logger.warning("psycopg not installed, skipping summarize_inactive_users")
        return []

    try:
        url = get_postgres_url()
        with psycopg.connect(url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM summarize_inactive_users()")
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description] if cur.description else []
                result = [dict(zip(columns, row)) for row in rows]
                
                if result:
                    logger.info(
                        "summarize_inactive_users: marked %d users for summarization",
                        len(result),
                    )
                return result

    except Exception as e:
        logger.error("Failed to call summarize_inactive_users: %s", e)
        return []


def get_users_needing_summary() -> list[dict[str, Any]]:
    """Get users tagged with 'needs_summary'.

    Returns:
        List of users needing summarization
    """
    if psycopg is None:
        logger.error("psycopg not installed")
        return []

    try:
        url = get_postgres_url()
        with psycopg.connect(url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT user_id, username, last_interaction_at
                    FROM {DBTable.USERS}
                    WHERE tags @> %s::jsonb
                    """,
                    ('["needs_summary"]',),
                )
                rows = cur.fetchall()
                return [dict(row) for row in rows]

    except Exception as e:
        logger.error("Failed to get users needing summary: %s", e)
        return []


def mark_user_summarized(user_id: int) -> None:
    """Mark user as summarized by updating tags.

    Removes 'needs_summary' and adds 'summarized' tag.
    """
    if psycopg is None:
        logger.error("psycopg not installed")
        return

    try:
        url = get_postgres_url()
        with psycopg.connect(url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Get current tags
                cur.execute(
                    f"""
                    SELECT tags FROM {DBTable.USERS}
                    WHERE user_id = %s
                    """,
                    (str(user_id),),
                )
                row = cur.fetchone()
                
                if not row:
                    logger.warning("User %s not found", user_id)
                    return
                
                current_tags = row.get("tags") or []
                
                # Update tags
                new_tags = [t for t in current_tags if t != "needs_summary"]
                if "summarized" not in new_tags:
                    new_tags.append("summarized")
                
                # Update tags
                import json
                cur.execute(
                    f"""
                    UPDATE {DBTable.USERS}
                    SET tags = %s::jsonb, updated_at = NOW()
                    WHERE user_id = %s
                    """,
                    (json.dumps(new_tags), str(user_id)),
                )
                conn.commit()
                logger.info("Marked user %s as summarized", user_id)

    except Exception as e:
        logger.error("Failed to mark user %s as summarized: %s", user_id, e)


def run_retention(
    session_id: str,
    message_store: MessageStore,
    now: datetime | None = None,
    user_id: int | None = None,
) -> str | None:
    """Summarise and prune when retention window passed.

    Returns the generated summary or None if no action was taken.
    """
    current_time = now or datetime.now(UTC)
    messages = message_store.list(session_id)

    if not _older_than_cutoff(messages, current_time):
        return None

    # Get user_id from messages if not provided
    if user_id is None and messages:
        user_id = messages[0].user_id

    cleaned_messages = _drop_human_tag(messages)
    summary_text = summarise_messages(cleaned_messages)

    # Save summary to users table if we have user_id
    if user_id:
        update_user_summary(user_id, summary_text)

    # Delete old messages from messages table
    message_store.delete(session_id)
    return summary_text
