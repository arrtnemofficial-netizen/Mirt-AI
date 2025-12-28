"""
Tests for photo purpose detection (SSOT).
"""

import pytest

from src.agents.langgraph.rules.photo_purpose import determine_photo_purpose
from src.agents.langgraph.state import create_initial_state


class TestPhotoPurpose:
    """Test photo purpose detection logic."""

    def test_first_photo_in_init(self):
        """First photo in INIT phase should route to vision."""
        state = create_initial_state(
            session_id="test_123",
            metadata={"has_image": True, "vision_greeted": False},
        )
        state["has_image"] = True
        state["dialog_phase"] = "INIT"
        
        purpose, reason = determine_photo_purpose(state)
        assert purpose == "product_ident"
        assert "first_photo" in reason

    def test_photo_in_payment_phase(self):
        """Photo in payment phase should route to payment (transactional)."""
        state = create_initial_state(
            session_id="test_123",
            metadata={"has_image": True, "vision_greeted": True},
        )
        state["has_image"] = True
        state["dialog_phase"] = "WAITING_FOR_PAYMENT_PROOF"
        
        purpose, reason = determine_photo_purpose(state)
        assert purpose == "transactional"
        assert "transactional_phase" in reason

    def test_smart_rerun_no_products(self):
        """Photo in mid-conversation with no products should rerun vision."""
        state = create_initial_state(
            session_id="test_123",
            metadata={"has_image": True, "vision_greeted": True},
        )
        state["has_image"] = True
        state["dialog_phase"] = "WAITING_FOR_SIZE"
        state["selected_products"] = []  # No products selected
        
        purpose, reason = determine_photo_purpose(state, user_message="")
        assert purpose == "product_ident"
        assert "smart_rerun" in reason

    def test_smart_rerun_asks_price(self):
        """Photo with 'цена' question should rerun vision."""
        state = create_initial_state(
            session_id="test_123",
            metadata={"has_image": True, "vision_greeted": True},
        )
        state["has_image"] = True
        state["dialog_phase"] = "WAITING_FOR_SIZE"
        state["selected_products"] = [{"name": "Костюм Ритм"}]  # Has products
        
        purpose, reason = determine_photo_purpose(state, user_message="Яка цена?")
        assert purpose == "product_ident"
        assert "smart_rerun" in reason

    def test_context_when_has_products(self):
        """Photo in mid-conversation with products should be context."""
        state = create_initial_state(
            session_id="test_123",
            metadata={"has_image": True, "vision_greeted": True},
        )
        state["has_image"] = True
        state["dialog_phase"] = "WAITING_FOR_SIZE"
        state["selected_products"] = [{"name": "Костюм Ритм"}]  # Has products
        
        purpose, reason = determine_photo_purpose(state, user_message="Ок")
        assert purpose == "context"
        assert "mid_conversation" in reason

    def test_explicit_new_product_trigger(self):
        """Explicit 'new product' trigger should route to vision."""
        state = create_initial_state(
            session_id="test_123",
            metadata={"has_image": True, "vision_greeted": True},
        )
        state["has_image"] = True
        state["dialog_phase"] = "WAITING_FOR_SIZE"
        
        purpose, reason = determine_photo_purpose(state, user_message="Додай новий товар")
        assert purpose == "product_ident"
        assert "explicit_new_product" in reason

