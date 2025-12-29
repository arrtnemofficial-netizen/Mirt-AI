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
    # Removed: crm, webhooks, llm queues (not used - only summarization+followups in Celery)
)

# Queue-specific time limits (seconds)
QUEUE_TIME_LIMITS = {
    "default": {"soft": 60, "hard": 120},
    "summarization": {"soft": 120, "hard": 180},
    "followups": {"soft": 30, "hard": 60},
    # Removed: crm, webhooks, llm time limits (queues not used)
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
        # NOTE: Memory cleanup, CRM, health, manychat, messages, llm_usage tasks are no longer in Celery.
        # They run synchronously or via BackgroundTasks, or are disabled.
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
# SIGNALS - Lifecycle hooks
# =============================================================================


@signals.setup_logging.connect
def setup_celery_logging(**kwargs):
    from src.core.logging import setup_logging

    is_production = os.getenv("PUBLIC_BASE_URL", "").strip() != "http://localhost:8000"
    is_railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))
    setup_logging(
        level=os.getenv("LOG_LEVEL", "INFO"),
        json_format=bool(is_production or is_railway),
        service_name="mirt-ai-worker",
    )


# =============================================================================
# TASK ROUTING
# =============================================================================

celery_app.conf.task_routes = {
    "src.workers.tasks.summarization.*": {"queue": "summarization"},
    "src.workers.tasks.followups.*": {"queue": "followups"},
    # NOTE: CRM, health, manychat, messages, llm_usage tasks are no longer in Celery.
}

# =============================================================================
# CELERY BEAT SCHEDULE - Periodic tasks
# =============================================================================

celery_app.conf.beat_schedule = {
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
    # NOTE: Memory cleanup, health, CRM, and LLM usage tasks are no longer scheduled via Celery Beat.
    # They should be handled via external cron or other scheduling mechanisms if needed.
}

# =============================================================================
# SIGNALS - Lifecycle hooks
# =============================================================================


@signals.worker_init.connect
def worker_init_handler(sender=None, **kwargs):
    """Called when worker process starts."""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                  MIRT AI - CELERY WORKER                     ║
║                  Worker Process Initialized                  ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)
    logger.info("=" * 60)
    logger.info("CELERY WORKER INITIALIZED: %s", sender)
    logger.info("=" * 60)

    # Log registered tasks
    task_list = sorted([name for name in celery_app.tasks.keys() if not name.startswith("celery.")])
    logger.info("Registered Tasks (%d):", len(task_list))
    for task_name in task_list[:10]:  # Show first 10
        logger.info("  - %s", task_name)
    if len(task_list) > 10:
        logger.info("  ... and %d more", len(task_list) - 10)

    # Log queues
    queue_names = [q.name for q in TASK_QUEUES]
    logger.info("Active Queues: %s", ", ".join(queue_names))


@signals.worker_process_init.connect
def worker_process_init_handler(sender=None, **kwargs):
    try:
        from src.agents.langgraph.checkpointer import warmup_checkpointer_pool
        from src.workers.sync_utils import run_sync

        run_sync(warmup_checkpointer_pool())
    except Exception as e:
        logger.warning("[CELERY] Checkpointer warmup skipped/failed: %s", e)


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
