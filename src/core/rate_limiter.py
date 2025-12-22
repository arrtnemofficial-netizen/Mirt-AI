"""Rate limiter for integrations (ManyChat, etc.).

Provides distributed rate limiting using Redis for multi-instance deployments.
Falls back to in-memory limiter if Redis is unavailable.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Global Redis client cache
_redis_client: object | None = None


def _get_redis_client():
    """Get or create Redis client."""
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    try:
        import os

        import redis

        from src.conf.config import settings

        redis_url = os.getenv("REDIS_URL") or settings.REDIS_URL
        if not redis_url:
            return None

        _redis_client = redis.from_url(redis_url, decode_responses=True)
        # Test connection
        _redis_client.ping()
        logger.info("Redis rate limiter connected")
        return _redis_client
    except Exception as e:
        logger.warning("Redis not available for rate limiting: %s", e)
        _redis_client = None
        return None


def check_rate_limit(key: str, *, requests_per_minute: int = 60, requests_per_hour: int = 1000) -> bool:
    """Check if request is within rate limits.

    Uses Redis sliding window algorithm for distributed rate limiting.
    Falls back to always allowing if Redis is unavailable.

    Args:
        key: Unique identifier for the rate limit (e.g., user_id, IP address)
        requests_per_minute: Maximum requests per minute
        requests_per_hour: Maximum requests per hour

    Returns:
        True if request is allowed, False if rate limit exceeded
    """
    redis_client = _get_redis_client()

    if not redis_client:
        # Fallback: allow all requests if Redis is unavailable
        # This prevents blocking when Redis is down
        logger.debug("Redis unavailable, allowing request (key=%s)", key)
        return True

    try:
        now = time.time()
        minute_key = f"rate_limit:minute:{key}"
        hour_key = f"rate_limit:hour:{key}"

        # Sliding window: use sorted sets
        pipe = redis_client.pipeline()

        # Minute window
        pipe.zremrangebyscore(minute_key, 0, now - 60)  # Remove old entries
        pipe.zcard(minute_key)  # Count current entries
        pipe.zadd(minute_key, {str(now): now})  # Add current request
        pipe.expire(minute_key, 60)  # Auto-expire

        # Hour window
        pipe.zremrangebyscore(hour_key, 0, now - 3600)  # Remove old entries
        pipe.zcard(hour_key)  # Count current entries
        pipe.zadd(hour_key, {str(now): now})  # Add current request
        pipe.expire(hour_key, 3600)  # Auto-expire

        results = pipe.execute()

        minute_count = results[1]  # Result of zcard for minute
        hour_count = results[4]  # Result of zcard for hour

        # Check limits
        if minute_count >= requests_per_minute:
            logger.warning(
                "Rate limit exceeded (minute) for key=%s: %d/%d requests",
                key,
                minute_count,
                requests_per_minute,
            )
            return False

        if hour_count >= requests_per_hour:
            logger.warning(
                "Rate limit exceeded (hour) for key=%s: %d/%d requests",
                key,
                hour_count,
                requests_per_hour,
            )
            return False

        return True

    except Exception as e:
        logger.error("Rate limit check failed for key=%s: %s", key, e)
        # Fail open: allow request if Redis check fails
        return True
