"""
E2E: Vision not-in-catalog escalation.
"""

import pytest

from src.agents.pydantic.models import ProductMatch, VisionResponse
from src.core.state_machine import State


@pytest.mark.asyncio
async def test_vision_not_in_catalog_escalates(monkeypatch):
    async def mock_run_vision(message, deps):
        return VisionResponse(
            reply_to_user="Unknown product",
            confidence=0.9,
            needs_clarification=False,
            identified_product=ProductMatch(
                name="Competitor Suit",
                price=0,
                color="",
            ),
        )

    async def mock_enrich(_name, color=None):
        return None

    async def mock_send(self, *args, **kwargs):
        return True

    import src.agents.langgraph.nodes.vision as vision_module
    import src.services.notification_service as notification_service

    monkeypatch.setattr(vision_module, "run_vision", mock_run_vision)
    monkeypatch.setattr(vision_module, "_enrich_product_from_db", mock_enrich)
    monkeypatch.setattr(
        notification_service.NotificationService, "send_escalation_alert", mock_send
    )

    state = {
        "session_id": "sess_vision_escalate",
        "trace_id": "trace_vision_escalate",
        "messages": [{"role": "user", "content": "What is this?"}],
        "has_image": True,
        "image_url": "https://example.com/test.jpg",
        "metadata": {"session_id": "sess_vision_escalate"},
        "current_state": State.STATE_2_VISION.value,
        "selected_products": [],
    }

    result = await vision_module.vision_node(state)

    assert result["dialog_phase"] == "COMPLETED"
    assert result["current_state"] == State.STATE_7_END.value
    assert result.get("escalation_level") == "HARD"
    assert result["metadata"].get("escalation_reason") == "product_not_in_catalog"
