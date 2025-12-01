"""Idempotency support for Celery tasks.

Prevents duplicate task execution using:
- Redis-based locks
- Task ID deduplication
- Webhook message_id tracking
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from typing import Any


logger = logging.getLogger(__name__)


def generate_task_key(
    task_name: str,
    *args: Any,
    **kwargs: Any,
) -> str:
    """Generate a unique idempotency key for a task.

    Args:
        task_name: Name of the task
        *args: Task positional arguments
        **kwargs: Task keyword arguments

    Returns:
        SHA256 hash as idempotency key
    """
    # Build string representation
    key_parts = [task_name]
    key_parts.extend(str(arg) for arg in args)
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))

    key_string = "|".join(key_parts)
    return hashlib.sha256(key_string.encode()).hexdigest()[:32]


def webhook_task_id(
    source: str,
    message_id: str | None,
    user_id: str,
    action: str,
) -> str:
    """Generate idempotent task_id from webhook data.

    Use this as task_id when dispatching tasks from webhooks
    to prevent duplicate processing of the same message.

    Args:
        source: Webhook source (telegram, manychat)
        message_id: Unique message ID from platform
        user_id: User identifier
        action: Action type (process_message, create_order, etc.)

    Returns:
        Deterministic task_id for this webhook event

    Example:
        task_id = webhook_task_id(
            source="telegram",
            message_id="12345",
            user_id="67890",
            action="process_message",
        )
        process_message.apply_async(args=[...], task_id=task_id)
    """
    key = f"{source}:{message_id}:{action}" if message_id else f"{source}:{user_id}:{action}"

    return hashlib.sha256(key.encode()).hexdigest()[:32]


class IdempotencyChecker:
    """Check and track idempotent task execution.

    Uses Redis to track processed task IDs.

    Example:
        checker = IdempotencyChecker(redis_client)

        if checker.is_processed(task_id):
            return {"status": "duplicate"}

        # ... process task ...

        checker.mark_processed(task_id)
    """

    def __init__(self, redis_client: Any, prefix: str = "mirt:idempotency"):
        self.redis = redis_client
        self.prefix = prefix
        self.default_ttl = timedelta(hours=24)

    def _key(self, task_id: str) -> str:
        return f"{self.prefix}:{task_id}"

    def is_processed(self, task_id: str) -> bool:
        """Check if task was already processed."""
        try:
            return self.redis.exists(self._key(task_id)) > 0
        except Exception as e:
            logger.warning("[IDEMPOTENCY] Redis check failed: %s", e)
            return False  # Allow processing if Redis fails

    def mark_processed(
        self,
        task_id: str,
        result: str = "ok",
        ttl: timedelta | None = None,
    ) -> None:
        """Mark task as processed."""
        try:
            key = self._key(task_id)
            expiry = ttl or self.default_ttl
            self.redis.setex(key, int(expiry.total_seconds()), result)
            logger.debug("[IDEMPOTENCY] Marked processed: %s", task_id)
        except Exception as e:
            logger.warning("[IDEMPOTENCY] Redis mark failed: %s", e)

    def get_result(self, task_id: str) -> str | None:
        """Get cached result for processed task."""
        try:
            result = self.redis.get(self._key(task_id))
            return result.decode() if result else None
        except Exception as e:
            logger.warning("[IDEMPOTENCY] Redis get failed: %s", e)
            return None


def get_idempotency_checker() -> IdempotencyChecker | None:
    """Get IdempotencyChecker instance if Redis is available."""
    try:
        import os

        import redis

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(redis_url)
        return IdempotencyChecker(client)
    except Exception as e:
        logger.warning("[IDEMPOTENCY] Failed to create checker: %s", e)
        return None
