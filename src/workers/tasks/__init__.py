"""Celery tasks for MIRT AI.

Tasks:
- summarization: Summarize old conversations and prune messages
- followups: Send follow-up messages to inactive users
- crm: Create orders in CRM system
"""

from src.workers.tasks.crm import create_crm_order
from src.workers.tasks.followups import (
    check_all_sessions_for_followups,
    send_followup,
)
from src.workers.tasks.summarization import (
    check_all_sessions_for_summarization,
    summarize_session,
)


__all__ = [
    "summarize_session",
    "check_all_sessions_for_summarization",
    "send_followup",
    "check_all_sessions_for_followups",
    "create_crm_order",
]
