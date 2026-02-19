"""Shared lifecycle registry for vision background tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any


logger = logging.getLogger(__name__)

_VISION_BG_TASKS: set[asyncio.Task] = set()


def register_vision_task(task: asyncio.Task) -> asyncio.Task:
    """Register a running vision-related task for graceful shutdown."""
    _VISION_BG_TASKS.add(task)
    task.add_done_callback(_VISION_BG_TASKS.discard)
    return task


def create_vision_task(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """Create and register a vision-related background task."""
    return register_vision_task(asyncio.create_task(coro))


def get_vision_background_task_count() -> int:
    """Return number of active registered vision tasks."""
    return len(_VISION_BG_TASKS)


async def shutdown_vision_background_tasks(timeout_s: float = 2.0) -> None:
    """Cancel and await all registered vision tasks."""
    if not _VISION_BG_TASKS:
        return

    tasks = list(_VISION_BG_TASKS)
    logger.info("[VISION] Shutting down %d background task(s)", len(tasks))
    for task in tasks:
        if not task.done():
            task.cancel()

    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout_s,
        )
    except TimeoutError:
        logger.warning("[VISION] Background task shutdown timed out after %.2fs", timeout_s)
    finally:
        _VISION_BG_TASKS.clear()
