"""
Rate Limiter - захист від flood/abuse.
======================================
Token bucket rate limiter для обмеження запитів per user.

Використання:
    from src.core.rate_limiter import RateLimiter, check_rate_limit

    if not check_rate_limit(user_id):
        return "Too many requests"
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """Token bucket для rate limiting."""

    capacity: int = 10  # Max tokens
    refill_rate: float = 1.0  # Tokens per second
    tokens: float = field(default=10.0)
    last_refill: float = field(default_factory=time.time)

    def consume(self, tokens: int = 1) -> bool:
        """
        Спробувати використати tokens.

        Returns:
            True якщо дозволено, False якщо rate limited
        """
        now = time.time()

        # Refill tokens based on time passed
        time_passed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + time_passed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True

        return False

    def reset(self) -> None:
        """Reset bucket to full capacity."""
        self.tokens = self.capacity
        self.last_refill = time.time()


class RateLimiter:
    """
    Rate limiter з per-user buckets.

    Args:
        capacity: Max requests per window
        refill_rate: Requests per second to refill
        cleanup_interval: Seconds between cleanup of old buckets
    """

    def __init__(
        self,
        capacity: int = 10,
        refill_rate: float = 1.0,
        cleanup_interval: float = 300.0,
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.cleanup_interval = cleanup_interval
        self._buckets: dict[str, TokenBucket] = {}
        self._last_cleanup = time.time()

    def check(self, key: str, tokens: int = 1) -> bool:
        """
        Перевірити чи дозволений запит для key.

        Args:
            key: User ID або інший ідентифікатор
            tokens: Кількість tokens для consume

        Returns:
            True якщо дозволено, False якщо rate limited
        """
        self._maybe_cleanup()

        if key not in self._buckets:
            self._buckets[key] = TokenBucket(
                capacity=self.capacity,
                refill_rate=self.refill_rate,
            )

        allowed = self._buckets[key].consume(tokens)

        if not allowed:
            logger.warning("Rate limit exceeded for key: %s", key[:20])

        return allowed

    def get_remaining(self, key: str) -> int:
        """Отримати залишок tokens для key."""
        if key not in self._buckets:
            return self.capacity
        return int(self._buckets[key].tokens)

    def reset(self, key: str) -> None:
        """Reset rate limit для key."""
        if key in self._buckets:
            self._buckets[key].reset()

    def _maybe_cleanup(self) -> None:
        """Cleanup старих buckets для економії пам'яті."""
        now = time.time()
        if now - self._last_cleanup < self.cleanup_interval:
            return

        self._last_cleanup = now
        cutoff = now - self.cleanup_interval

        # Remove buckets that haven't been used recently
        old_keys = [k for k, v in self._buckets.items() if v.last_refill < cutoff]

        for key in old_keys:
            del self._buckets[key]

        if old_keys:
            logger.debug("Cleaned up %d rate limit buckets", len(old_keys))

    def get_stats(self) -> dict[str, Any]:
        """Отримати статистику rate limiter."""
        return {
            "active_buckets": len(self._buckets),
            "capacity": self.capacity,
            "refill_rate": self.refill_rate,
        }


# =============================================================================
# GLOBAL RATE LIMITERS
# =============================================================================

# Default rate limiter: 10 requests per 10 seconds per user
_default_limiter = RateLimiter(capacity=10, refill_rate=1.0)

# Strict rate limiter for expensive operations: 3 per minute
_strict_limiter = RateLimiter(capacity=3, refill_rate=0.05)

# Lenient rate limiter for cheap operations: 30 per 30 seconds
_lenient_limiter = RateLimiter(capacity=30, refill_rate=1.0)


def check_rate_limit(user_id: str, tokens: int = 1) -> bool:
    """Перевірити default rate limit для user."""
    return _default_limiter.check(user_id, tokens)


def check_strict_rate_limit(user_id: str) -> bool:
    """Перевірити strict rate limit (для LLM calls)."""
    return _strict_limiter.check(user_id, 1)


def get_rate_limit_remaining(user_id: str) -> int:
    """Отримати залишок requests для user."""
    return _default_limiter.get_remaining(user_id)


def reset_rate_limit(user_id: str) -> None:
    """Reset rate limit для user (наприклад після /restart)."""
    _default_limiter.reset(user_id)
    _strict_limiter.reset(user_id)


def get_all_rate_limit_stats() -> dict[str, Any]:
    """Отримати статистику всіх rate limiters."""
    return {
        "default": _default_limiter.get_stats(),
        "strict": _strict_limiter.get_stats(),
        "lenient": _lenient_limiter.get_stats(),
    }
