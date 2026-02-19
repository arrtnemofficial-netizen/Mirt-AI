from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.pydantic.models import VisionResponse
from src.core.models import ProductMatch
from src.core.state_machine import State


class _BrokenCatalogRow(dict):
    def __setitem__(self, key, value):  # pragma: no cover - behavior is the test trigger
        raise RuntimeError("merge_failed")


@pytest.mark.asyncio
async def test_vision_emits_metric_for_color_option_merge_fallback():
    from src.agents.langgraph.nodes.vision import vision_node

    state = {
        "session_id": "vision_fallback",
        "current_state": State.STATE_2_VISION.value,
        "messages": [{"role": "user", "content": "що це", "image_url": "https://example.com/a.jpg"}],
        "image_url": "https://example.com/a.jpg",
        "has_image": True,
        "selected_products": [],
        "metadata": {"session_id": "vision_fallback", "has_image": True},
        "step_number": 1,
    }

    response = VisionResponse(
        reply_to_user="Знайшла модель",
        identified_product=ProductMatch(
            id=0,
            name="Лагуна",
            price=0,
            color="",
            photo_url="https://example.com/photo.jpg",
        ),
        confidence=0.91,
        needs_clarification=False,
    )

    with patch(
        "src.agents.langgraph.nodes.vision.run_vision",
        new=AsyncMock(return_value=response),
    ), patch(
        "src.agents.langgraph.nodes.vision._enrich_product_from_db",
        new=AsyncMock(
            return_value={
                "_catalog_row": _BrokenCatalogRow({"id": 1, "name": "Лагуна", "price": 1990}),
                "_color_options": ["чорний", "білий"],
                "_ambiguous_color": True,
            }
        ),
    ), patch(
        "src.agents.langgraph.nodes.vision._build_vision_messages",
        return_value=[{"type": "text", "content": "ok"}],
    ), patch(
        "src.agents.langgraph.nodes.vision.should_escalate_vision",
        return_value=(False, None),
    ), patch(
        "src.agents.langgraph.nodes.vision.log_trace",
        new=AsyncMock(return_value=None),
    ), patch(
        "src.agents.langgraph.nodes.vision.track_metric",
    ) as track_metric_mock:
        result = await vision_node(state)

    assert result["current_state"] in {
        State.STATE_3_SIZE_COLOR.value,
        State.STATE_2_VISION.value,
    }
    assert any(
        (
            call.args
            and call.args[0] == "fallback_triggered"
            and isinstance(call.args[2], dict)
            and call.args[2].get("fallback_reason") == "vision_color_options_merge_failed"
        )
        for call in track_metric_mock.call_args_list
    )
