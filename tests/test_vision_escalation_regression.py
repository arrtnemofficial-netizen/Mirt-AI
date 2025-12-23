"""
Regression Tests: Vision Dual-Track Escalation.
===============================================
Tests that vision escalation works correctly with dual-track (user message + Telegram notification).
"""

import sys
from pathlib import Path
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

# Add project root to path
root = Path(__file__).resolve().parents[1]
project_root = str(root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.langgraph.nodes.vision import vision_node
from src.agents.langgraph.state import create_initial_state
from src.core.state_machine import State
from src.agents.pydantic.models import VisionResponse, ProductMatch


class TestVisionEscalationRegression:
    """Regression tests for vision escalation behavior."""

    @pytest.mark.asyncio
    async def test_vision_not_identified_escalates_with_dual_track(self):
        """When vision cannot identify product, should escalate with dual-track."""
        state = create_initial_state(
            session_id="test_vision_not_identified",
            messages=[{"role": "user", "content": "Що це?"}],
            metadata={"channel": "instagram", "has_image": True},
        )
        state["current_state"] = State.STATE_0_INIT.value
        state["has_image"] = True
        
        # Mock vision agent to return no product identified
        with patch("src.agents.langgraph.nodes.vision.run_vision") as mock_vision:
            mock_response = VisionResponse(
                reply_to_user="Не впевнена. Зараз уточню по цьому товару наявність 🙌🏻",
                identified_product=None,
                confidence=0.3,  # Low confidence
                needs_clarification=True,
                clarification_question="Що саме на фото?",
            )
            mock_vision.return_value = mock_response
            
            # Mock manager notification + ensure background task is scheduled
            real_create_task = asyncio.create_task
            with (
                patch("src.services.notification_service.NotificationService") as mock_notif_service,
                patch("src.agents.langgraph.nodes.vision.asyncio.create_task") as mock_create_task,
            ):
                mock_notif_instance = AsyncMock()
                mock_notif_service.return_value = mock_notif_instance
                mock_notif_instance.send_escalation_alert = AsyncMock(return_value=True)
                mock_create_task.side_effect = real_create_task

                result = await vision_node(state)
                # Let fire-and-forget task run
                await asyncio.sleep(0)
                
                # Check that escalation happened
                assert result["dialog_phase"] == "ESCALATED", (
                    f"Vision not identified should escalate, got phase {result['dialog_phase']}"
                )
                assert result.get("escalation_level") == "SOFT"
                
                # Check that user got soft message
                messages = result.get("messages", [])
                assert len(messages) >= 2, "Should have at least 2 messages (greeting + escalation)"
                message_text = " ".join([m.get("content", "") for m in messages]).lower()
                assert "уточню" in message_text or "наявність" in message_text, (
                    "User message should have soft escalation tone"
                )
                
                # Check that notification was scheduled (fire-and-forget)
                assert mock_create_task.called, "Expected background notification task to be scheduled"

    @pytest.mark.asyncio
    async def test_vision_product_not_in_catalog_escalates(self):
        """When vision identifies product but it's not in catalog, should escalate."""
        state = create_initial_state(
            session_id="test_vision_not_in_catalog",
            messages=[{"role": "user", "content": "Що це?"}],
            metadata={"channel": "instagram", "has_image": True},
        )
        state["current_state"] = State.STATE_0_INIT.value
        state["has_image"] = True
        
        # Mock vision agent to return product not in catalog
        with patch("src.agents.langgraph.nodes.vision.run_vision") as mock_vision:
            mock_response = VisionResponse(
                reply_to_user="Зараз уточню по цьому товару наявність 🙌🏻",
                identified_product=ProductMatch(
                    id=0,
                    name="Конкурентний товар",
                    price=0.0,
                    size=None,
                    color="",
                    photo_url="",
                ),
                confidence=0.8,
                needs_clarification=False,
            )
            mock_vision.return_value = mock_response
            
            # Mock catalog enrichment to return None (not found)
            with patch("src.agents.langgraph.nodes.vision._enrich_product_from_db") as mock_enrich:
                mock_enrich.return_value = None  # Product not in catalog
                
                real_create_task = asyncio.create_task
                with (
                    patch("src.services.notification_service.NotificationService") as mock_notif_service,
                    patch("src.agents.langgraph.nodes.vision.asyncio.create_task") as mock_create_task,
                ):
                    mock_notif_instance = AsyncMock()
                    mock_notif_service.return_value = mock_notif_instance
                    mock_notif_instance.send_escalation_alert = AsyncMock(return_value=True)
                    mock_create_task.side_effect = real_create_task

                    result = await vision_node(state)
                    await asyncio.sleep(0)
                    
                    # Check escalation
                    assert result["dialog_phase"] == "ESCALATED", (
                        f"Product not in catalog should escalate, got phase {result['dialog_phase']}"
                    )
                    assert result.get("escalation_level") == "SOFT"
                    assert mock_create_task.called, "Expected background notification task to be scheduled"

