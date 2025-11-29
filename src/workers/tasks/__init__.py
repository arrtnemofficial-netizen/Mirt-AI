"""Celery tasks for MIRT AI.

Tasks:
- summarization: Summarize old conversations and prune messages
- followups: Send follow-up messages to inactive users
- crm: Create orders in CRM system
- health: Worker health checks
- messages: Message processing
- llm_usage: LLM token usage tracking
"""

from src.workers.tasks.crm import (
    check_pending_orders,
    create_crm_order,
    sync_order_status,
)
from src.workers.tasks.followups import (
    check_all_sessions_for_followups,
    send_followup,
)
from src.workers.tasks.health import ping, worker_health_check
from src.workers.tasks.llm_usage import (
    aggregate_daily_usage,
    get_user_usage_summary,
    record_usage,
)
from src.workers.tasks.messages import process_message, send_response
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
    "check_all_sessions_for_followups",
    # CRM
    "create_crm_order",
    "sync_order_status",
    "check_pending_orders",
    # Health
    "worker_health_check",
    "ping",
    # Messages
    "process_message",
    "send_response",
    # LLM Usage
    "record_usage",
    "get_user_usage_summary",
    "aggregate_daily_usage",
]
