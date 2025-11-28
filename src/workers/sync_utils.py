"""Sync utilities for Celery workers.

Celery workers run in sync context. This module provides utilities
to safely call async code without creating new event loops per task.

Uses anyio.from_thread to reuse a single event loop per worker process.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
from typing import Any, Callable, Coroutine, TypeVar


logger = logging.getLogger(__name__)

T = TypeVar("T")

# Thread-local storage for event loop
_loop_holder = threading.local()


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Get or create an event loop for the current thread."""
    loop = getattr(_loop_holder, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _loop_holder.loop = loop
        logger.debug(
            "[SYNC_UTILS] Created new event loop for thread %s", threading.current_thread().name
        )
    return loop


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously.

    This is the ONLY way to call async code from Celery tasks.
    Reuses event loop per worker thread to avoid overhead.

    Args:
        coro: Async coroutine to run

    Returns:
        Result of the coroutine

    Example:
        result = run_sync(some_async_function(arg1, arg2))
    """
    loop = _get_or_create_loop()
    try:
        return loop.run_until_complete(coro)
    except Exception:
        # Don't close loop on error - it can be reused
        raise


def sync_wrapper(async_func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., T]:
    """Decorator to create sync version of async function.

    Usage:
        @sync_wrapper
        async def my_async_func(x):
            return await something(x)

        # Now can call synchronously:
        result = my_async_func(42)
    """

    @functools.wraps(async_func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return run_sync(async_func(*args, **kwargs))

    return wrapper


def cleanup_loop() -> None:
    """Clean up the event loop for current thread.

    Call this when worker process is shutting down.
    """
    loop = getattr(_loop_holder, "loop", None)
    if loop is not None and not loop.is_closed():
        try:
            # Cancel all pending tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            # Run until all tasks are cancelled
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            logger.debug(
                "[SYNC_UTILS] Cleaned up event loop for thread %s", threading.current_thread().name
            )
        except Exception as e:
            logger.warning("[SYNC_UTILS] Error cleaning up loop: %s", e)
        finally:
            _loop_holder.loop = None
