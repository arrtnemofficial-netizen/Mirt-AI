"""Generic circuit breaker for external API calls.

Provides circuit breaker pattern for protecting against cascading failures
when external services are unavailable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, TypeVar

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, don't try
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class CircuitBreaker:
    """Generic circuit breaker for external services.

    Prevents cascading failures by temporarily disabling failing services.
    """

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0  # seconds
    half_open_max_calls: int = 1

    state: CircuitState = field(default=CircuitState.CLOSED)
    failure_count: int = field(default=0)
    success_count: int = field(default=0)
    last_failure_time: float = field(default=0.0)
    half_open_calls: int = field(default=0)

    def record_success(self) -> None:
        """Record successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_max_calls:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                self.half_open_calls = 0
                logger.info("[CIRCUIT:%s] Recovered, state=CLOSED", self.name)
        else:
            self.failure_count = 0
            self.state = CircuitState.CLOSED
            self.half_open_calls = 0

    def record_failure(self) -> None:
        """Record failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            # Failure in half-open state - go back to open
            self.state = CircuitState.OPEN
            self.half_open_calls = 0
            logger.warning("[CIRCUIT:%s] Failed in HALF_OPEN, state=OPEN", self.name)
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "[CIRCUIT:%s] OPEN after %d failures",
                self.name,
                self.failure_count,
            )

    def can_execute(self) -> bool:
        """Check if circuit allows execution."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if recovery timeout passed
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                self.success_count = 0
                logger.info("[CIRCUIT:%s] Transitioning to HALF_OPEN", self.name)
                return True
            return False

        # HALF_OPEN: allow limited calls
        if self.half_open_calls < self.half_open_max_calls:
            self.half_open_calls += 1
            return True
        return False

    def get_status(self) -> dict[str, Any]:
        """Get current circuit breaker status."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "can_execute": self.can_execute(),
        }


# Global circuit breakers registry
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str, **kwargs: Any) -> CircuitBreaker:
    """Get or create circuit breaker by name."""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name=name, **kwargs)
    return _circuit_breakers[name]


def circuit_breaker(name: str, **breaker_kwargs: Any) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for applying circuit breaker to async functions."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        breaker = get_circuit_breaker(name, **breaker_kwargs)

        async def wrapper(*args: Any, **kwargs: Any) -> T:
            if not breaker.can_execute():
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{name}' is OPEN. Service unavailable."
                )

            try:
                result = await func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception as e:
                breaker.record_failure()
                raise

        return wrapper  # type: ignore[return-value]

    return decorator


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and request is rejected."""

    pass

