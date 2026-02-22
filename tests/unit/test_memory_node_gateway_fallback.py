from __future__ import annotations

from typing import Any

import pytest

from src.agents.langgraph.nodes.memory import memory_context_node
from src.agents.langgraph.state import create_initial_state


class FailingGateway:
    async def fetch_context(self, session_id: str, limit: int, min_importance: float) -> None:
        raise RuntimeError("db down")

    async def upsert_fact(
        self,
        session_id: str,
        fact: Any,
        importance: float,
        confidence: float,
        source: str,
    ) -> Any:
        raise RuntimeError("not used")

    async def decay_or_cleanup(self, now_utc: Any) -> Any:
        raise RuntimeError("not used")


@pytest.mark.asyncio
async def test_memory_context_node_gracefully_falls_back_on_gateway_error(monkeypatch) -> None:
    import src.agents.langgraph.nodes.memory as memory_node

    monkeypatch.setattr(memory_node, "get_memory_gateway", lambda: FailingGateway())

    state = create_initial_state(
        session_id="session-1",
        metadata={"user_id": "user-1"},
    ).model_dump()

    result = await memory_context_node(state)

    assert result["step_number"] == 1
    assert "memory_profile" not in result
