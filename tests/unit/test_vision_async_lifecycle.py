from __future__ import annotations

import asyncio

import pytest

from src.agents.langgraph.nodes import vision as vision_module


@pytest.mark.asyncio
async def test_shutdown_vision_background_tasks_cancels_pending_tasks():
    async def _never_finishes() -> None:
        await asyncio.sleep(60)

    task = vision_module._register_bg_task(asyncio.create_task(_never_finishes()))
    assert vision_module.get_vision_background_task_count() >= 1

    await vision_module.shutdown_vision_background_tasks(timeout_s=0.5)

    assert task.cancelled() or task.done()
    assert vision_module.get_vision_background_task_count() == 0


@pytest.mark.asyncio
async def test_shutdown_vision_background_tasks_is_noop_when_empty():
    await vision_module.shutdown_vision_background_tasks(timeout_s=0.1)
    assert vision_module.get_vision_background_task_count() == 0
