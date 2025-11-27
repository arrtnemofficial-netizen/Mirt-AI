import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.conf.config import settings
from src.core.constants import MessageTag, DBTable
from src.services.message_store import MessageStore, StoredMessage
from src.services.supabase_client import get_supabase_client

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
        client.table(DBTable.USERS).upsert({
            "user_id": user_id,
            "summary": summary,
        }).execute()
    except Exception as e:
        logger.error("Failed to update summary for user %s: %s", user_id, e)


def run_retention(
    session_id: str, 
    message_store: MessageStore, 
    now: Optional[datetime] = None,
    user_id: int | None = None,
) -> Optional[str]:
    """Summarise and prune when retention window passed.

    Returns the generated summary or None if no action was taken.
    """
    current_time = now or datetime.now(timezone.utc)
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

