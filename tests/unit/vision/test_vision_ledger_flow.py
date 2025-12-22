from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.agents.langgraph.nodes.vision.node import vision_node
from src.services.domain.vision import vision_ledger
from src.agents.langgraph.state import create_initial_state

@pytest.mark.asyncio
async def test_vision_ledger_status_transitions(monkeypatch):
    """Verify that vision_node records final statuses in the ledger."""
    vision_ledger.reset_in_memory_vision_ledger()
    ledger = vision_ledger.get_vision_ledger()

    # Stub vision agent response
    class _ProductStub:
        def __init__(self) -> None:
            self.name = "Test product"
            self.color = "black"
        def model_dump(self) -> dict:
            return {"name": self.name, "color": self.color}

    response_mock = MagicMock()
    response_mock.identified_product = _ProductStub()
    response_mock.needs_clarification = False
    response_mock.confidence = 0.95
    response_mock.reply_to_user = "Found it!"

    monkeypatch.setattr("src.agents.langgraph.nodes.vision.node.run_vision", AsyncMock(return_value=response_mock))
    monkeypatch.setattr("src.agents.langgraph.nodes.vision.node.enrich_product_from_db", AsyncMock(return_value={"_catalog_row": {"id": "p1"}}))
    monkeypatch.setattr("src.agents.langgraph.nodes.vision.node.build_vision_messages", lambda **kwargs: [{"type": "text", "text": "result"}])

    state = create_initial_state(
        session_id="test_session",
        user_message="Find this",
        metadata={"image_url": "https://example.com/img.jpg"}
    )

    result = await vision_node(state)
    
    # Check if ledger recorded processed status
    hash_key = result["metadata"]["vision_hash_processed"]
    record = ledger.get_by_hash(hash_key)
    
    assert record is not None
    assert record["status"] == vision_ledger.LEDGER_STATUS_PROCESSED
    assert record["vision_result_id"] == result["metadata"]["vision_result_id"]
    assert result["agent_response"]["metadata"]["vision_result_id"] == record["vision_result_id"]
