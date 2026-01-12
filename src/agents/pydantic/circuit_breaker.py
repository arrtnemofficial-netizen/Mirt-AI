"""
Circuit breaker for LLM API calls.

This module provides agent-specific circuit breakers that wrap the core
CircuitBreaker implementation from src/core/circuit_breaker.

Architecture:
- Core CircuitBreaker: src/core/circuit_breaker.py (SSOT for pattern)
- This module: Agent-specific wrappers with metrics integration
"""

import logging
from typing import Any, Callable

from src.core.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
)
from src.services.observability import track_metric

from .exceptions import AgentNetworkError

logger = logging.getLogger(__name__)


class LLMCircuitBreaker:
    """
    LLM-specific circuit breaker wrapper.
    
    Wraps the core CircuitBreaker with:
    - Async-first interface
    - Metrics integration
    - Agent-specific error handling
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        name: str = "llm_circuit",
    ):
        """
        Initialize LLM circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before trying half-open
            half_open_max_calls: Max calls allowed in half-open state (mapped to success_threshold)
            name: Name for metrics/logging
        """
        self.name = name
        self.half_open_max_calls = half_open_max_calls
        
        # Use core CircuitBreaker as the implementation
        self._breaker = get_circuit_breaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=half_open_max_calls,
        )

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._breaker.state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._breaker.failure_count

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
            AgentNetworkError: If circuit is open or call fails
        """
        # Check if circuit allows execution
        if not self._breaker.can_execute():
            logger.warning(
                "[CIRCUIT_BREAKER] %s circuit is OPEN, rejecting request",
                self.name,
            )
            track_metric(f"{self.name}_circuit_rejected", 1)
            raise AgentNetworkError(
                f"Circuit breaker is OPEN for {self.name}. Service unavailable."
            )

        # Execute function
        try:
            result = await func(*args, **kwargs)
            self._breaker.record_success()
            return result
        except Exception as e:
            self._breaker.record_failure(e)
            
            # Track circuit state changes
            if self._breaker.state == CircuitState.OPEN:
                track_metric(f"{self.name}_circuit_opened", 1)
            
            raise


# =============================================================================
# GLOBAL CIRCUIT BREAKERS (Agent-Specific Singletons)
# =============================================================================

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


# Re-export for convenience
__all__ = [
    "LLMCircuitBreaker",
    "CircuitState",
    "get_support_circuit_breaker",
    "get_vision_circuit_breaker",
    "get_payment_circuit_breaker",
]
