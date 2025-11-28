# Celery Workers Architecture

## Overview

MIRT AI uses Celery for background task processing with Redis as the message broker.

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   FastAPI       │────▶│     Redis       │◀────│  Celery Worker  │
│   (dispatcher)  │     │   (broker)      │     │  (12 tasks)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                │
                                ▼
                        ┌─────────────────┐
                        │  Celery Beat    │
                        │  (scheduler)    │
                        └─────────────────┘
```

## Queues

| Queue           | Purpose               | Time Limit | Prefetch |
| --------------- | --------------------- | ---------- | -------- |
| `llm`           | AI message processing | 60s        | 1        |
| `summarization` | Session summarization | 120s       | 1        |
| `followups`     | Follow-up reminders   | 60s        | 1        |
| `crm`           | CRM order creation    | 30s        | 1        |
| `webhooks`      | Response delivery     | 30s        | 1        |
| `default`       | Health checks, misc   | 10s        | 1        |

## Tasks

### Message Processing

```python
# src/workers/tasks/messages.py

@shared_task(queue="llm", soft_time_limit=55, time_limit=60)
def process_message(session_id, user_message, platform, chat_id, ...):
    """Main task - process message through AI agent."""
    ...

@shared_task(queue="llm", soft_time_limit=85, time_limit=90)
def process_and_respond(session_id, user_message, platform, chat_id, ...):
    """Fire-and-forget: process + send response."""
    ...

@shared_task(queue="webhooks", soft_time_limit=25, time_limit=30)
def send_response(platform, chat_id, response_text, ...):
    """Send response to Telegram/ManyChat."""
    ...
```

### Summarization

```python
# src/workers/tasks/summarization.py

@shared_task(queue="summarization", soft_time_limit=110, time_limit=120)
def summarize_session(session_id, user_id=None):
    """Summarize conversation and clean old messages."""
    ...

@shared_task(queue="summarization")
def check_all_sessions_for_summarization():
    """Periodic: queue summarization for eligible sessions."""
    ...
```

### Follow-ups

```python
# src/workers/tasks/followups.py

@shared_task(queue="followups", soft_time_limit=55, time_limit=60)
def send_followup(session_id, channel="telegram", chat_id=None):
    """Send follow-up reminder."""
    ...

@shared_task(queue="followups")
def check_all_sessions_for_followups():
    """Periodic: check and send follow-ups."""
    ...
```

### CRM

```python
# src/workers/tasks/crm.py

@shared_task(queue="crm", soft_time_limit=25, time_limit=30)
def create_crm_order(order_data):
    """Create order in Snitkix CRM."""
    ...
```

### Health

```python
# src/workers/tasks/health.py

@shared_task(queue="default")
def ping():
    """Simple connectivity test."""
    return {"pong": True, "timestamp": ...}

@shared_task(queue="default")
def worker_health_check():
    """Check Redis and Supabase connectivity."""
    ...
```

## Dispatcher

The dispatcher routes tasks to Celery or sync execution based on `CELERY_ENABLED`:

```python
from src.workers.dispatcher import dispatch_message

# When CELERY_ENABLED=true
result = dispatch_message(
    session_id="12345",
    user_message="Привіт!",
    platform="telegram",
    chat_id="67890",
    fire_and_forget=True,  # Don't wait for result
)
# Returns: {"queued": True, "task_id": "abc123", "trace_id": "xyz789"}

# When CELERY_ENABLED=false
result = dispatch_message(...)
# Returns: {"queued": False, "response": "...", "trace_id": "xyz789"}
```

## Exception Handling

```python
# src/workers/exceptions.py

class RetryableError(Exception):
    """Transient error - will be retried."""
    pass

class PermanentError(Exception):
    """Business logic error - no retry."""
    def __init__(self, message, error_code=None):
        self.error_code = error_code

class RateLimitError(RetryableError):
    """Rate limit - retry after delay."""
    def __init__(self, message, retry_after=60):
        self.retry_after = retry_after

class ExternalServiceError(RetryableError):
    """External API failure."""
    def __init__(self, service, message):
        self.service = service

class DatabaseError(RetryableError):
    """Database operation failure."""
    pass
```

Usage in tasks:

```python
@shared_task(
    autoretry_for=(RetryableError,),  # Auto-retry these
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def my_task():
    try:
        # ... do work
    except PermanentError:
        raise  # Don't retry
    except SomeTransientError as e:
        raise ExternalServiceError("api", str(e)) from e  # Will retry
```

## Sync Utils

For calling async code from sync Celery tasks:

```python
# src/workers/sync_utils.py

from src.workers.sync_utils import run_sync

@shared_task
def my_task():
    # DON'T DO THIS:
    # asyncio.run(async_func())  # Creates new event loop each time!
    
    # DO THIS:
    result = run_sync(async_func())  # Reuses event loop
```

## Idempotency

Prevent duplicate task execution:

```python
# src/workers/idempotency.py

from src.workers.idempotency import webhook_task_id

# Generate deterministic task ID from webhook data
task_id = webhook_task_id(
    source="telegram",
    message_id="12345",
    user_id="67890",
    action="process",
)
# Returns: "telegram:process:a1b2c3d4"

# Use as task_id
task = process_message.apply_async(..., task_id=task_id)
# If task with same ID already exists, it won't be duplicated
```

## Beat Schedule

Periodic tasks configured in `celery_app.py`:

```python
celery_app.conf.beat_schedule = {
    "health-check-5min": {
        "task": "src.workers.tasks.health.worker_health_check",
        "schedule": 300.0,  # 5 minutes
    },
    "followups-check-15min": {
        "task": "src.workers.tasks.followups.check_all_sessions_for_followups",
        "schedule": 900.0,  # 15 minutes
    },
    "summarization-check-1h": {
        "task": "src.workers.tasks.summarization.check_all_sessions_for_summarization",
        "schedule": 3600.0,  # 1 hour
    },
}
```

## Configuration

### Environment Variables

```env
REDIS_URL=redis://localhost:6379/0
CELERY_ENABLED=true
CELERY_EAGER=false           # true for testing (sync execution)
CELERY_CONCURRENCY=4
CELERY_MAX_TASKS_PER_CHILD=100
```

### Key Settings

```python
# src/workers/celery_app.py

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    
    # Reliability
    task_acks_late=True,              # ACK after completion
    task_reject_on_worker_lost=True,  # Requeue on crash
    worker_prefetch_multiplier=1,     # One task at a time
    
    # Memory management
    worker_max_tasks_per_child=100,   # Restart after N tasks
    
    # Retry
    task_default_retry_delay=60,
    task_max_retries=3,
)
```

## Testing

Run with eager mode (sync execution):

```python
# tests/test_workers_integration.py

import os
os.environ["CELERY_EAGER"] = "true"

from src.workers.tasks.messages import process_message

# Task runs synchronously
result = process_message("session", "Hello")
assert result["status"] == "success"
```

Run tests:

```bash
pytest tests/test_workers_integration.py -v
```

## Monitoring

### Flower UI

```bash
# Docker
docker-compose --profile monitoring up -d

# Manual
celery -A src.workers.celery_app flower --port=5555
```

### CLI Commands

```bash
# List workers
celery -A src.workers.celery_app inspect active

# Queue status
celery -A src.workers.celery_app inspect stats

# Registered tasks
celery -A src.workers.celery_app inspect registered

# Purge all tasks
celery -A src.workers.celery_app purge
```

### Signals

```python
# src/workers/celery_app.py

@signals.worker_init.connect
def worker_init_handler(sender=None, **kwargs):
    logger.info("[CELERY] Worker initialized: %s", sender)

@signals.task_failure.connect
def task_failure_handler(task_id=None, exception=None, **kwargs):
    if isinstance(exception, PermanentError):
        logger.warning("[CELERY] Permanent failure: %s", task_id)
    else:
        logger.error("[CELERY] Task failed: %s - %s", task_id, exception)
```
