"""
Circuit Breaker - захист від каскадних відмов.
==============================================
Патерн Circuit Breaker для зовнішніх API:
- ManyChat API
- LLM (Grok/GPT)

Стани:
- CLOSED: нормальна робота
- OPEN: відмова, повертаємо fallback
- HALF_OPEN: тестуємо чи сервіс відновився

Використання:
    from src.core.circuit_breaker import circuit_breaker, CircuitState

    @circuit_breaker("manychat", failure_threshold=3, recovery_timeout=30)
    async def call_manychat_api():
        ...
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar


if TYPE_CHECKING:
    from collections.abc import Callable


logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Стан circuit breaker."""

    CLOSED = "closed"  # Нормальна робота
    OPEN = "open"  # Відмова, блокуємо запити
    HALF_OPEN = "half_open"  # Тестуємо відновлення


@dataclass
class CircuitBreaker:
    """
    Circuit Breaker для захисту від каскадних відмов.

    Args:
        name: Ім'я сервісу (для логування)
        failure_threshold: Кількість помилок до відкриття
        recovery_timeout: Секунди до спроби відновлення
        success_threshold: Успішних запитів для закриття
    """

    name: str
    failure_threshold: int = 3
    recovery_timeout: float = 30.0
    success_threshold: int = 2

    # Internal state
    state: CircuitState = field(default=CircuitState.CLOSED)
    failure_count: int = field(default=0)
    success_count: int = field(default=0)
    last_failure_time: float = field(default=0.0)

    def __post_init__(self):
        logger.info(
            "CircuitBreaker[%s] initialized: threshold=%d, recovery=%ds",
            self.name,
            self.failure_threshold,
            self.recovery_timeout,
        )

    def can_execute(self) -> bool:
        """Перевірка чи можна виконати запит."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Перевіряємо чи минув recovery timeout
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)
                return True
            return False

        # HALF_OPEN - дозволяємо один запит для тесту
        return True

    def record_success(self) -> None:
        """Записати успішний запит."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self._transition_to(CircuitState.CLOSED)
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0

    def record_failure(self, error: Exception | None = None) -> None:
        """Записати невдалий запит."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        logger.warning(
            "CircuitBreaker[%s] failure %d/%d: %s",
            self.name,
            self.failure_count,
            self.failure_threshold,
            str(error)[:100] if error else "unknown",
        )

        if self.state == CircuitState.HALF_OPEN:
            # Одна помилка в HALF_OPEN = назад в OPEN
            self._transition_to(CircuitState.OPEN)
        elif self.failure_count >= self.failure_threshold:
            self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Перехід до нового стану."""
        old_state = self.state
        self.state = new_state

        if new_state == CircuitState.CLOSED:
            self.failure_count = 0
            self.success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self.success_count = 0

        logger.info(
            "CircuitBreaker[%s] state: %s → %s", self.name, old_state.value, new_state.value
        )

    def reset(self) -> None:
        """Примусовий reset circuit breaker."""
        self._transition_to(CircuitState.CLOSED)
        logger.info("CircuitBreaker[%s] manually reset", self.name)


# =============================================================================
# GLOBAL CIRCUIT BREAKERS
# =============================================================================

_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 3,
    recovery_timeout: float = 30.0,
    success_threshold: int = 2,
) -> CircuitBreaker:
    """Отримати або створити circuit breaker за ім'ям."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=success_threshold,
        )
    return _breakers[name]


# Pre-defined breakers for main services
MANYCHAT_BREAKER = get_circuit_breaker("manychat", failure_threshold=3, recovery_timeout=30)
LLM_BREAKER = get_circuit_breaker("llm", failure_threshold=2, recovery_timeout=45)


# =============================================================================
# DECORATOR
# =============================================================================

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised when circuit is open and request is blocked."""

    def __init__(self, breaker_name: str):
        self.breaker_name = breaker_name
        super().__init__(f"Circuit breaker '{breaker_name}' is OPEN")


def circuit_breaker(
    name: str,
    failure_threshold: int = 3,
    recovery_timeout: float = 30.0,
    fallback: Callable[..., Any] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator для захисту функції circuit breaker'ом.

    Args:
        name: Ім'я breaker'а
        failure_threshold: Кількість помилок до відкриття
        recovery_timeout: Секунди до спроби відновлення
        fallback: Fallback функція при відкритому circuit

    Usage:
        @circuit_breaker("manychat", failure_threshold=3, fallback=lambda: {"ok": False})
        async def call_manychat():
            ...
    """
    breaker = get_circuit_breaker(name, failure_threshold, recovery_timeout)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            if not breaker.can_execute():
                logger.warning(
                    "CircuitBreaker[%s] OPEN - returning fallback for %s", name, func.__name__
                )
                if fallback:
                    return fallback(*args, **kwargs)
                raise CircuitOpenError(name)

            try:
                result = await func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception as e:
                breaker.record_failure(e)
                if fallback:
                    return fallback(*args, **kwargs)
                raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            if not breaker.can_execute():
                logger.warning(
                    "CircuitBreaker[%s] OPEN - returning fallback for %s", name, func.__name__
                )
                if fallback:
                    return fallback(*args, **kwargs)
                raise CircuitOpenError(name)

            try:
                result = func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception as e:
                breaker.record_failure(e)
                if fallback:
                    return fallback(*args, **kwargs)
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def get_all_breaker_states() -> dict[str, dict[str, Any]]:
    """Отримати стан всіх circuit breakers (для health check)."""
    return {
        name: {
            "state": breaker.state.value,
            "failure_count": breaker.failure_count,
            "last_failure": breaker.last_failure_time,
        }
        for name, breaker in _breakers.items()
    }


def reset_all_breakers() -> None:
    """Скинути всі circuit breakers (для тестування)."""
    for breaker in _breakers.values():
        breaker.reset()
