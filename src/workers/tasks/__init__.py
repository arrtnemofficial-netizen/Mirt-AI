"""Celery tasks for MIRT AI.

Celery is only used for:
- summarization: Summarize old conversations and prune messages
- followups: Send follow-up messages to inactive users

All other processing (ManyChat messages, CRM orders, etc.) runs synchronously
or via FastAPI BackgroundTasks, not Celery.
"""

from src.workers.tasks.followups import (
    check_all_sessions_for_followups,
    handle_24h_followup_escalation,
    schedule_followup,
    send_followup,
)
from src.workers.tasks.summarization import (
    check_all_sessions_for_summarization,
    summarize_session,
    summarize_user_history,
)


__all__ = [
    # Summarization
    "summarize_session",
    "summarize_user_history",
    "check_all_sessions_for_summarization",
    # Followups
    "send_followup",
    "schedule_followup",
    "check_all_sessions_for_followups",
    "handle_24h_followup_escalation",
]
