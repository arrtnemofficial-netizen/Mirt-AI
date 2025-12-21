"""Configurable follow-up scheduling utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.conf.config import settings
from src.core.constants import MessageTag
from src.services.infra.message_store import MessageStore, StoredMessage


if TYPE_CHECKING:
    from collections.abc import Iterable


def _parse_schedule(schedule: Iterable[float | int] | None) -> list[float]:
    """Parse schedule hours, supporting both int and float values."""
    if schedule is None:
        return [float(h) for h in settings.followup_schedule_hours]
    hours: list[float] = []
    for value in schedule:
        if isinstance(value, int | float) and value > 0:
            hours.append(float(value))
    return hours


def _followups_sent(messages: list[StoredMessage]) -> int:
    count = 0
    for msg in messages:
        if any(MessageTag.is_followup_tag(tag) for tag in msg.tags):
            count += 1
    return count


def _last_activity(messages: list[StoredMessage]) -> datetime | None:
    if not messages:
        return None
    return messages[-1].created_at


def next_followup_due_at(
    messages: list[StoredMessage],
    schedule_hours: Iterable[float | int] | None = None,
) -> datetime | None:
    """Return when the next follow-up should occur based on activity and sent count."""

    schedule = _parse_schedule(schedule_hours)
    if not schedule:
        return None

    sent = _followups_sent(messages)
    if sent >= len(schedule):
        return None

    last = _last_activity(messages)
    if not last:
        return None

    return last + timedelta(hours=schedule[sent])


def build_followup_message(
    session_id: str, index: int, now: datetime | None = None
) -> StoredMessage:
    from src.core.prompt_registry import get_snippet_by_header

    created_at = now or datetime.now(UTC)
    
    snippet_name = f"FOLLOWUP_{index}"
    s = get_snippet_by_header(snippet_name)
    content = "".join(s) if s else "Hi! Just checking in."

    return StoredMessage(
        session_id=session_id,
        role="assistant",
        content=content,
        created_at=created_at,
        tags=[MessageTag.followup_tag(index)],
    )


def run_followups(
    session_id: str,
    message_store: MessageStore,
    now: datetime | None = None,
    schedule_hours: Iterable[float | int] | None = None,
) -> StoredMessage | None:
    """Create and persist a follow-up message if the schedule is due.

    Returns the StoredMessage when a follow-up is created, otherwise None.
    """

    messages = message_store.list(session_id)
    due_at = next_followup_due_at(messages, schedule_hours=schedule_hours)
    current_time = now or datetime.now(UTC)

    if not due_at or current_time < due_at:
        return None

    sent = _followups_sent(messages)
    followup = build_followup_message(session_id, index=sent + 1, now=current_time)
    message_store.append(followup)
    return followup

