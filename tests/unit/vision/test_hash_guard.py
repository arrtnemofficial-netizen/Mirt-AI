from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from src.agents.langgraph.nodes.vision.node import _compute_vision_hash
from src.agents.langgraph.nodes.vision.node import vision_node
from src.agents.langgraph.state import create_initial_state


@pytest.mark.asyncio
async def test_vision_duplicate_hash_guard(monkeypatch):
    """Vision node should detect duplicate photos and avoid reprocessing."""
    from src.services.domain.vision.vision_ledger import reset_in_memory_vision_ledger
    from src.agents.langgraph.nodes.vision.node import get_vision_ledger
    from src.conf.config import settings

    # Force in-memory ledger
    monkeypatch.setattr(settings, "SUPABASE_URL", None)
    monkeypatch.setattr(settings, "SUPABASE_API_KEY", None)
    get_vision_ledger.cache_clear()
    reset_in_memory_vision_ledger()

    class _ProductStub:
        def __init__(self) -> None:
            self.name = "Test"
            self.color = "black"

        def model_dump(self) -> dict[str, str]:
            return {"name": self.name, "color": self.color}

    response_mock = AsyncMock()
    response_mock.identified_product = _ProductStub()
    response_mock.needs_clarification = False
    response_mock.confidence = 0.9
    response_mock.reply_to_user = "ok"

    run_vision_mock = AsyncMock(return_value=response_mock)
    monkeypatch.setattr("src.agents.langgraph.nodes.vision.node.run_vision", run_vision_mock)
    monkeypatch.setattr("src.agents.langgraph.nodes.vision.node.enrich_product_from_db", AsyncMock(return_value={"_catalog_row": {}}))
    monkeypatch.setattr("src.agents.langgraph.nodes.vision.node.build_vision_messages", lambda **kwargs: [{"type": "text", "text": "hi"}])

    state = create_initial_state(
        session_id="s1",
        user_message="Ось фото",
        metadata={"image_url": "https://test/image.jpg"},
    )

    first = await vision_node(state)
    
    assert first["metadata"].get("vision_hash_processed")
    assert run_vision_mock.call_count == 1

    # Clear cache to ensure fresh ledger instance sees the recorded result
    get_vision_ledger.cache_clear()
    
    state.update(first)
    second = await vision_node(state)

    assert second["metadata"].get("vision_duplicate_detected") is True
    assert run_vision_mock.call_count == 1  # Should still be 1, not 2
