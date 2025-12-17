"""Celery application configuration.

Production-ready configuration with:
- Separate queues with time limits
- Proper prefetch and ACK settings
- Memory leak prevention (max_tasks_per_child)
- Centralized retry policy
- Eager mode for testing
"""

from __future__ import annotations

import logging
import os
import ssl

from celery import Celery, signals
from kombu import Queue

from src.workers.exceptions import PermanentError, RateLimitError, RetryableError


logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION FROM ENVIRONMENT
# =============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_TLS = os.getenv("REDIS_TLS", "false").lower() == "true"

# Feature flags
CELERY_ENABLED = os.getenv("CELERY_ENABLED", "false").lower() == "true"
CELERY_EAGER = os.getenv("CELERY_EAGER", "false").lower() == "true"  # For testing

# Worker limits
WORKER_CONCURRENCY = int(os.getenv("CELERY_CONCURRENCY", "4"))
WORKER_MAX_TASKS = int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", "100"))
WORKER_PREFETCH = int(os.getenv("CELERY_PREFETCH", "1"))

# =============================================================================
# QUEUE DEFINITIONS
# =============================================================================

TASK_QUEUES = (
    Queue("default", routing_key="default"),
    Queue("summarization", routing_key="summarization"),
    Queue("followups", routing_key="followups"),
    Queue("crm", routing_key="crm"),
    Queue("webhooks", routing_key="webhooks"),
    Queue("llm", routing_key="llm"),  # For LLM pipeline tasks
)

# Queue-specific time limits (seconds)
QUEUE_TIME_LIMITS = {
    "default": {"soft": 60, "hard": 120},
    "summarization": {"soft": 120, "hard": 180},
    "followups": {"soft": 30, "hard": 60},
    "crm": {"soft": 30, "hard": 60},
    "webhooks": {"soft": 10, "hard": 20},
    "llm": {"soft": 90, "hard": 120},
}

# =============================================================================
# CELERY APP
# =============================================================================

# Build broker options
broker_options = {}
if REDIS_TLS:
    broker_options["ssl"] = {
        "ssl_cert_reqs": ssl.CERT_REQUIRED,
    }

celery_app = Celery(
    "mirt_workers",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "src.workers.tasks.summarization",
        "src.workers.tasks.followups",
        "src.workers.tasks.crm",
        "src.workers.tasks.health",
        "src.workers.tasks.manychat",
        "src.workers.tasks.messages",  # THE MAIN TASK!
        "src.workers.tasks.llm_usage",  # Token usage tracking
    ],
)

# =============================================================================
# CELERY CONFIGURATION
# =============================================================================

celery_app.conf.update(
    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # -------------------------------------------------------------------------
    # Queues
    # -------------------------------------------------------------------------
    task_queues=TASK_QUEUES,
    task_default_queue="default",
    task_default_routing_key="default",
    # -------------------------------------------------------------------------
    # ACK/Prefetch - CRITICAL for reliability
    # -------------------------------------------------------------------------
    task_acks_late=True,  # ACK only after task completes
    task_reject_on_worker_lost=True,  # Requeue if worker dies
    worker_prefetch_multiplier=WORKER_PREFETCH,  # 1 = fair distribution
    # -------------------------------------------------------------------------
    # Time limits
    # -------------------------------------------------------------------------
    task_soft_time_limit=60,  # Default soft limit
    task_time_limit=120,  # Default hard limit
    # -------------------------------------------------------------------------
    # Worker settings
    # -------------------------------------------------------------------------
    worker_concurrency=WORKER_CONCURRENCY,
    worker_max_tasks_per_child=WORKER_MAX_TASKS,  # Prevent memory leaks
    worker_disable_rate_limits=False,
    # -------------------------------------------------------------------------
    # Rate limiting
    # -------------------------------------------------------------------------
    task_default_rate_limit="100/m",
    # -------------------------------------------------------------------------
    # Results
    # -------------------------------------------------------------------------
    result_expires=86400,  # 24 hours
    result_extended=True,  # Store task args/kwargs
    # -------------------------------------------------------------------------
    # Retry defaults
    # -------------------------------------------------------------------------
    task_autoretry_for=(RetryableError,),
    task_retry_backoff=True,
    task_retry_backoff_max=600,  # Max 10 min between retries
    task_retry_jitter=True,  # Add randomness to prevent thundering herd
    # -------------------------------------------------------------------------
    # Testing mode
    # -------------------------------------------------------------------------
    task_always_eager=CELERY_EAGER,  # Run tasks synchronously in tests
    task_eager_propagates=CELERY_EAGER,  # Propagate exceptions in eager mode
    # -------------------------------------------------------------------------
    # Broker options
    # -------------------------------------------------------------------------
    broker_transport_options=broker_options,
    broker_connection_retry_on_startup=True,
)

# =============================================================================
# TASK ROUTING
# =============================================================================

celery_app.conf.task_routes = {
    "src.workers.tasks.summarization.*": {"queue": "summarization"},
    "src.workers.tasks.followups.*": {"queue": "followups"},
    "src.workers.tasks.crm.*": {"queue": "crm"},
    "src.workers.tasks.manychat.*": {"queue": "llm"},
    "src.workers.tasks.messages.process_message": {"queue": "llm"},
    "src.workers.tasks.messages.process_and_respond": {"queue": "llm"},
    "src.workers.tasks.messages.send_response": {"queue": "webhooks"},
    "src.workers.tasks.health.*": {"queue": "default"},
    "src.workers.tasks.llm_usage.*": {"queue": "default"},
}

# =============================================================================
# CELERY BEAT SCHEDULE - Periodic tasks
# =============================================================================

celery_app.conf.beat_schedule = {
    # Health check every 5 minutes
    "health-check-5min": {
        "task": "src.workers.tasks.health.worker_health_check",
        "schedule": 300.0,  # 5 minutes
        "options": {"queue": "default"},
    },
    # Check for follow-ups every 15 minutes
    "followups-check-15min": {
        "task": "src.workers.tasks.followups.check_all_sessions_for_followups",
        "schedule": 900.0,  # 15 minutes
        "options": {"queue": "followups"},
    },
    # Check for summarization every hour
    "summarization-check-1h": {
        "task": "src.workers.tasks.summarization.check_all_sessions_for_summarization",
        "schedule": 3600.0,  # 1 hour
        "options": {"queue": "summarization"},
    },
    # Check pending orders every 30 minutes
    "crm-orders-check-30min": {
        "task": "src.workers.tasks.crm.check_pending_orders",
        "schedule": 1800.0,  # 30 minutes
        "options": {"queue": "crm"},
    },
    # Aggregate LLM usage daily at midnight
    "llm-usage-daily": {
        "task": "src.workers.tasks.llm_usage.aggregate_daily_usage",
        "schedule": 86400.0,  # 24 hours
        "options": {"queue": "default"},
    },
}

# =============================================================================
# SIGNALS - Lifecycle hooks
# =============================================================================


@signals.worker_init.connect
def worker_init_handler(sender=None, **kwargs):
    """Called when worker process starts."""
    logger.info("[CELERY] Worker initialized: %s", sender)


@signals.worker_shutdown.connect
def worker_shutdown_handler(sender=None, **kwargs):
    """Called when worker process shuts down."""
    from src.workers.sync_utils import cleanup_loop

    cleanup_loop()
    logger.info("[CELERY] Worker shutdown: %s", sender)


@signals.task_prerun.connect
def task_prerun_handler(task_id=None, task=None, args=None, **kwargs):
    """Called before task execution."""
    logger.debug("[CELERY] Task starting: %s[%s]", task.name if task else "?", task_id)


@signals.task_postrun.connect
def task_postrun_handler(task_id=None, task=None, state=None, **kwargs):
    """Called after task execution."""
    logger.debug(
        "[CELERY] Task completed: %s[%s] state=%s", task.name if task else "?", task_id, state
    )


@signals.task_failure.connect
def task_failure_handler(task_id=None, exception=None, **kwargs):
    """Called when task fails."""
    if isinstance(exception, PermanentError):
        logger.warning("[CELERY] Task permanent failure: %s - %s", task_id, exception)
    elif isinstance(exception, RateLimitError):
        logger.warning("[CELERY] Task rate limited: %s - %s", task_id, exception)
    else:
        logger.error("[CELERY] Task failed: %s - %s", task_id, exception)
