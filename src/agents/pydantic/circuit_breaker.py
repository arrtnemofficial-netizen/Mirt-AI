"""
Circuit breaker for LLM API calls.

Prevents cascading failures by stopping requests when failure threshold is reached.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, TypeVar

from src.services.observability import track_metric

from .exceptions import AgentError, AgentLLMError, AgentNetworkError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class LLMCircuitBreaker:
    """
    Circuit breaker for LLM API calls.

    Prevents cascading failures by:
    1. Tracking failures
    2. Opening circuit when threshold reached
    3. Allowing limited requests in half-open state
    4. Closing circuit when service recovers
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        name: str = "llm_circuit",
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before trying half-open
            half_open_max_calls: Max calls allowed in half-open state
            name: Name for metrics/logging
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.name = name

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: float | None = None
        self.half_open_calls = 0
        self._lock = asyncio.Lock()

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to call
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            AgentError: If circuit is open or call fails
        """
        async with self._lock:
            # Check if circuit should transition
            await self._check_state_transition()

            # Reject if circuit is open
            if self.state == CircuitState.OPEN:
                logger.warning(
                    "[CIRCUIT_BREAKER] %s circuit is OPEN, rejecting request",
                    self.name,
                )
                track_metric(f"{self.name}_circuit_rejected", 1)
                raise AgentNetworkError(
                    f"Circuit breaker is OPEN for {self.name}. Service unavailable."
                )

            # Limit calls in half-open state
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.half_open_max_calls:
                    logger.warning(
                        "[CIRCUIT_BREAKER] %s circuit HALF_OPEN limit reached, rejecting",
                        self.name,
                    )
                    track_metric(f"{self.name}_circuit_rejected", 1)
                    raise AgentNetworkError(
                        f"Circuit breaker HALF_OPEN limit reached for {self.name}."
                    )
                self.half_open_calls += 1

        # Execute function
        try:
            result = await func(*args, **kwargs)
            await self._record_success()
            return result
        except (AgentNetworkError, AgentLLMError) as e:
            await self._record_failure()
            raise
        except Exception as e:
            # Don't count non-agent errors as circuit breaker failures
            raise

    async def _check_state_transition(self) -> None:
        """Check and update circuit breaker state."""
        now = time.time()

        # Transition from OPEN to HALF_OPEN after recovery timeout
        if self.state == CircuitState.OPEN:
            if (
                self.last_failure_time is not None
                and now - self.last_failure_time >= self.recovery_timeout
            ):
                logger.info(
                    "[CIRCUIT_BREAKER] %s circuit transitioning OPEN -> HALF_OPEN",
                    self.name,
                )
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                self.success_count = 0
                track_metric(f"{self.name}_circuit_state", 1, {"state": "half_open"})

        # Transition from HALF_OPEN to CLOSED on success
        elif self.state == CircuitState.HALF_OPEN:
            if self.success_count >= self.half_open_max_calls:
                logger.info(
                    "[CIRCUIT_BREAKER] %s circuit transitioning HALF_OPEN -> CLOSED",
                    self.name,
                )
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                self.half_open_calls = 0
                track_metric(f"{self.name}_circuit_state", 1, {"state": "closed"})

    async def _record_success(self) -> None:
        """Record successful call."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
            elif self.state == CircuitState.CLOSED:
                # Reset failure count on success
                self.failure_count = 0

    async def _record_failure(self) -> None:
        """Record failed call."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            # Transition to OPEN if threshold reached
            if self.failure_count >= self.failure_threshold:
                if self.state != CircuitState.OPEN:
                    logger.error(
                        "[CIRCUIT_BREAKER] %s circuit transitioning to OPEN "
                        "(failures: %d/%d)",
                        self.name,
                        self.failure_count,
                        self.failure_threshold,
                    )
                    self.state = CircuitState.OPEN
                    track_metric(f"{self.name}_circuit_state", 1, {"state": "open"})
                    track_metric(f"{self.name}_circuit_opened", 1)

            # Transition from HALF_OPEN to OPEN on failure
            elif self.state == CircuitState.HALF_OPEN:
                logger.warning(
                    "[CIRCUIT_BREAKER] %s circuit HALF_OPEN -> OPEN (failure detected)",
                    self.name,
                )
                self.state = CircuitState.OPEN
                self.half_open_calls = 0
                track_metric(f"{self.name}_circuit_state", 1, {"state": "open"})


# Global circuit breakers per agent
_support_circuit_breaker: LLMCircuitBreaker | None = None
_vision_circuit_breaker: LLMCircuitBreaker | None = None
_payment_circuit_breaker: LLMCircuitBreaker | None = None


def get_support_circuit_breaker() -> LLMCircuitBreaker:
    """Get or create support agent circuit breaker."""
    global _support_circuit_breaker
    if _support_circuit_breaker is None:
        _support_circuit_breaker = LLMCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            half_open_max_calls=3,
            name="support_agent",
        )
    return _support_circuit_breaker


def get_vision_circuit_breaker() -> LLMCircuitBreaker:
    """Get or create vision agent circuit breaker."""
    global _vision_circuit_breaker
    if _vision_circuit_breaker is None:
        _vision_circuit_breaker = LLMCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            half_open_max_calls=3,
            name="vision_agent",
        )
    return _vision_circuit_breaker


def get_payment_circuit_breaker() -> LLMCircuitBreaker:
    """Get or create payment agent circuit breaker."""
    global _payment_circuit_breaker
    if _payment_circuit_breaker is None:
        _payment_circuit_breaker = LLMCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            half_open_max_calls=3,
            name="payment_agent",
        )
    return _payment_circuit_breaker

