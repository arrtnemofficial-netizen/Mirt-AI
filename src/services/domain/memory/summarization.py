"""Summarization service for conversation history.

Handles:
- Summarizing old conversations after SUMMARY_RETENTION_DAYS
- Saving summaries to mirt_users table
- Pruning old messages from mirt_messages
- Integration with Supabase function summarize_inactive_users
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.conf.config import settings
from src.core.constants import DBTable, MessageTag
from src.services.infra.message_store import MessageStore, StoredMessage
from src.services.infra.supabase_client import get_supabase_client


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
    """Update summary field in mirt_users table."""
    client = get_supabase_client()
    if not client:
        return

    try:
        client.table(DBTable.USERS).upsert(
            {
                "user_id": user_id,
                "summary": summary,
            }
        ).execute()
    except Exception as e:
        logger.error("Failed to update summary for user %s: %s", user_id, e)


def call_summarize_inactive_users() -> list[dict[str, Any]]:
    """Call Supabase function summarize_inactive_users.

    This function marks users as needing summary after 3 days of inactivity.
    It's called by the periodic summarization task.

    The Supabase function:
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
    client = get_supabase_client()
    if not client:
        logger.warning("Supabase not configured, skipping summarize_inactive_users")
        return []

    try:
        response = client.rpc("summarize_inactive_users").execute()

        if response.data:
            logger.info(
                "summarize_inactive_users: marked %d users for summarization",
                len(response.data),
            )
            return response.data
        return []

    except Exception as e:
        logger.error("Failed to call summarize_inactive_users: %s", e)
        return []


def get_users_needing_summary() -> list[dict[str, Any]]:
    """Get users tagged with 'needs_summary'.

    Returns:
        List of users needing summarization
    """
    client = get_supabase_client()
    if not client:
        return []

    try:
        response = (
            client.table(DBTable.USERS)
            .select("user_id, username, last_interaction_at")
            .contains("tags", ["needs_summary"])
            .execute()
        )
        return response.data or []

    except Exception as e:
        logger.error("Failed to get users needing summary: %s", e)
        return []


def mark_user_summarized(user_id: int) -> None:
    """Mark user as summarized by updating tags.

    Removes 'needs_summary' and adds 'summarized' tag.
    """
    client = get_supabase_client()
    if not client:
        return

    try:
        # Get current tags
        response = (
            client.table(DBTable.USERS).select("tags").eq("user_id", user_id).single().execute()
        )

        current_tags = response.data.get("tags", []) if response.data else []

        # Update tags
        new_tags = [t for t in current_tags if t != "needs_summary"]
        if "summarized" not in new_tags:
            new_tags.append("summarized")

        client.table(DBTable.USERS).update(
            {
                "tags": new_tags,
            }
        ).eq("user_id", user_id).execute()

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

    # Save summary to mirt_users if we have user_id
    if user_id:
        update_user_summary(user_id, summary_text)

    # Delete old messages from mirt_messages
    message_store.delete(session_id)
    return summary_text
