"""Configurable follow-up scheduling utilities."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from src.conf.config import settings
from src.core.constants import MessageTag
from src.services.message_store import MessageStore, StoredMessage


def _parse_schedule(schedule: Optional[Iterable[int]]) -> List[int]:
    if schedule is None:
        return settings.followup_schedule_hours
    hours: List[int] = []
    for value in schedule:
        if isinstance(value, int) and value > 0:
            hours.append(value)
    return hours


def _followups_sent(messages: list[StoredMessage]) -> int:
    count = 0
    for msg in messages:
        if any(MessageTag.is_followup_tag(tag) for tag in msg.tags):
            count += 1
    return count


def _last_activity(messages: list[StoredMessage]) -> Optional[datetime]:
    if not messages:
        return None
    return messages[-1].created_at


def next_followup_due_at(
    messages: list[StoredMessage],
    schedule_hours: Optional[Iterable[int]] = None,
) -> Optional[datetime]:
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


def build_followup_message(session_id: str, index: int, now: Optional[datetime] = None) -> StoredMessage:
    created_at = now or datetime.now(timezone.utc)
    content = (
        "Привіт! Нагадуємо про підбір луку від MIRT. Готові повернутися до замовлення?"
        if index == 1
        else "Нагадування: ми зберегли ваші вподобання. Напишіть, якщо ще потрібна допомога."
    )
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
    now: Optional[datetime] = None,
    schedule_hours: Optional[Iterable[int]] = None,
) -> Optional[StoredMessage]:
    """Create and persist a follow-up message if the schedule is due.

    Returns the StoredMessage when a follow-up is created, otherwise None.
    """

    messages = message_store.list(session_id)
    due_at = next_followup_due_at(messages, schedule_hours=schedule_hours)
    current_time = now or datetime.now(timezone.utc)

    if not due_at or current_time < due_at:
        return None

    sent = _followups_sent(messages)
    followup = build_followup_message(session_id, index=sent + 1, now=current_time)
    message_store.append(followup)
    return followup
