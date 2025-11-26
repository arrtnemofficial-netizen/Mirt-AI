"""Summarisation and retention policies for long-running sessions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from src.conf.config import settings
from src.core.constants import MessageTag
from src.services.message_store import MessageStore, StoredMessage
from src.services.supabase_client import get_supabase_client


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


def update_user_summary(session_id: str, summary: str) -> None:
    client = get_supabase_client()
    if not client:
        return
    client.table(settings.SUPABASE_USERS_TABLE).upsert(
        {"session_id": session_id, "summary": summary}
    ).execute()


def run_retention(session_id: str, message_store: MessageStore, now: Optional[datetime] = None) -> Optional[str]:
    """Summarise and prune when retention window passed.

    Returns the generated summary or None if no action was taken.
    """

    current_time = now or datetime.now(timezone.utc)
    messages = message_store.list(session_id)
    if not _older_than_cutoff(messages, current_time):
        return None

    cleaned_messages = _drop_human_tag(messages)
    summary_text = summarise_messages(cleaned_messages)
    update_user_summary(session_id, summary_text)
    message_store.delete(session_id)
    return summary_text

