"""
Retry logic for agent calls with exponential backoff.

This module provides a retry decorator for transient errors (network, rate limits).
"""

import asyncio
import logging
from functools import wraps
from typing import Any, Callable, TypeVar

from src.services.observability import track_metric

from .exceptions import AgentError, AgentLLMError, AgentNetworkError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def exponential_backoff(initial: float = 1.0, max: float = 10.0, multiplier: float = 2.0):
    """
    Create exponential backoff function.

    Args:
        initial: Initial delay in seconds
        max: Maximum delay in seconds
        multiplier: Multiplier for each retry

    Returns:
        Function that takes retry attempt number and returns delay in seconds
    """
    def backoff(attempt: int) -> float:
        delay = initial * (multiplier ** (attempt - 1))
        return min(delay, max)
    return backoff


def retry_agent_call(
    max_retries: int = 3,
    retry_on: tuple[type[Exception], ...] = (AgentNetworkError, AgentLLMError),
    backoff: Callable[[int], float] | None = None,
):
    """
    Retry decorator for agent calls with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        retry_on: Tuple of exception types to retry on (default: AgentNetworkError, AgentLLMError)
        backoff: Backoff function (default: exponential_backoff)

    Usage:
        @retry_agent_call(max_retries=3, retry_on=(AgentNetworkError, AgentLLMError))
        async def run_support(...):
            ...
    """
    if backoff is None:
        backoff = exponential_backoff(initial=1.0, max=10.0)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None

            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = backoff(attempt)
                        logger.warning(
                            "[RETRY] %s failed (attempt %d/%d): %s. Retrying in %.2fs...",
                            func.__name__,
                            attempt,
                            max_retries,
                            str(e)[:100],
                            delay,
                        )
                        track_metric(
                            f"agent_{func.__name__}_retry",
                            1,
                            {"attempt": attempt, "error_type": type(e).__name__},
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "[RETRY] %s failed after %d attempts: %s",
                            func.__name__,
                            max_retries,
                            str(e)[:100],
                        )
                        track_metric(
                            f"agent_{func.__name__}_retry_exhausted",
                            1,
                            {"error_type": type(e).__name__},
                        )
                        raise
                except AgentError:
                    # Don't retry on other AgentError types (validation, timeout)
                    raise
                except Exception as e:
                    # Don't retry on unknown exceptions
                    raise

            # Should never reach here, but for type safety
            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed after {max_retries} attempts")

        return wrapper

    return decorator

