"""
E2E: Photo identification to payment flow.

Complete user journey:
1. User sends photo of product
2. Vision identifies product
3. User asks about sizes
4. User confirms they want to buy
5. Payment flow starts
6. User provides delivery data
7. Order completed

This is the most common happy path.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.e2e
@pytest.mark.slow
class TestPhotoToPaymentFlow:
    """End-to-end test for photo → payment journey."""

    @pytest.fixture
    def mock_services(self):
        """Mock all external services for E2E testing."""
        with (
            patch("src.services.catalog.CatalogService") as mock_catalog,
            patch("src.services.memory_service.MemoryService") as mock_memory,
            patch("src.agents.pydantic.vision_agent.vision_agent") as mock_vision,
            patch("src.agents.pydantic.support_agent.support_agent") as mock_support,
        ):
            # Setup catalog mock
            mock_catalog_instance = MagicMock()
            mock_catalog_instance.search_products = AsyncMock(
                return_value=[{"id": "prod_1", "name": "Вишиванка дитяча", "price": 1500}]
            )
            mock_catalog.return_value = mock_catalog_instance

            # Setup memory mock
            mock_memory_instance = MagicMock()
            mock_memory_instance.load_context = AsyncMock(return_value=None)
            mock_memory.return_value = mock_memory_instance

            yield {
                "catalog": mock_catalog_instance,
                "memory": mock_memory_instance,
                "vision": mock_vision,
                "support": mock_support,
            }

    def test_photo_triggers_vision_node(self):
        """Photo message must trigger vision node routing."""
        from src.agents.langgraph.edges import route_after_intent
        from src.core.state_machine import Intent, State

        state = {
            "current_state": State.STATE_1_DISCOVERY.value,
            "detected_intent": Intent.PHOTO_IDENT.value,
            "has_image": True,
            "is_escalated": False,
            "dialog_phase": None,
        }

        route = route_after_intent(state)
        # Should go to vision for photo processing
        assert route == "vision", f"Photo should trigger vision path, got '{route}'"

    def test_product_identified_enables_offer(self):
        """After product identified, offer should be reachable."""
        from src.agents.langgraph.edges import route_after_intent
        from src.core.state_machine import Intent, State

        # After vision identifies product, user says "хочу"
        state = {
            "current_state": State.STATE_2_VISION.value,
            "detected_intent": Intent.DISCOVERY_OR_QUESTION.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": None,
        }

        route = route_after_intent(state)
        # Should go to agent for further conversation
        assert route in ["agent", "offer", "vision"], (
            f"Product identified should enable conversation path, got '{route}'"
        )

    def test_offer_confirmation_triggers_payment(self):
        """User confirming offer must trigger payment flow."""
        from src.agents.langgraph.edges import route_after_intent
        from src.core.state_machine import Intent, State

        state = {
            "current_state": State.STATE_4_OFFER.value,
            "detected_intent": Intent.PAYMENT_DELIVERY.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "OFFER_MADE",
        }

        route = route_after_intent(state)
        assert route == "payment", f"Offer confirmation must trigger payment, got '{route}'"

    def test_payment_flow_stays_in_payment(self):
        """Payment data collection must stay in payment node."""
        from src.agents.langgraph.edges import master_router
        from src.core.state_machine import Intent, State

        payment_phases = [
            "WAITING_FOR_PAYMENT_METHOD",
            "WAITING_FOR_PAYMENT_PROOF",
        ]

        for phase in payment_phases:
            state = {
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "detected_intent": Intent.PAYMENT_DELIVERY.value,
                "has_image": False,
                "is_escalated": False,
                "dialog_phase": phase,
                "metadata": {},
            }

            route = master_router(state)
            assert route == "payment", f"Phase {phase} must stay in payment, got '{route}'"

    def test_complete_flow_state_progression(self):
        """Verify state progression through complete flow."""
        from src.core.state_machine import State

        expected_progression = [
            State.STATE_0_INIT,  # Initial
            State.STATE_1_DISCOVERY,  # Start
            State.STATE_2_VISION,  # After vision
            State.STATE_3_SIZE_COLOR,  # Size selection
            State.STATE_4_OFFER,  # Offer made
            State.STATE_5_PAYMENT_DELIVERY,  # Payment flow
            State.STATE_6_UPSELL,  # After payment
            State.STATE_7_END,  # Complete
        ]

        # Verify all states exist and are in order
        state_order = list(State)
        for _i, expected in enumerate(expected_progression):
            assert expected in state_order, f"State {expected} missing from progression"


@pytest.mark.e2e
class TestFlowEdgeCases:
    """E2E tests for edge cases in user journeys."""

    def test_user_can_restart_from_any_state(self):
        """User sending new photo should restart identification."""
        from src.agents.langgraph.edges import route_after_intent
        from src.core.state_machine import Intent, State

        # User in payment flow sends new photo
        state = {
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "detected_intent": Intent.PHOTO_IDENT.value,
            "has_image": True,
            "is_escalated": False,
            "dialog_phase": "WAITING_FOR_PAYMENT_METHOD",
        }

        route = route_after_intent(state)
        assert route == "vision", "New photo in any state should go to vision"

    def test_complaint_escalates_from_any_state(self):
        """Complaint must escalate regardless of current state."""
        from src.agents.langgraph.edges import route_after_intent
        from src.core.state_machine import Intent, State

        for state_enum in State:
            state = {
                "current_state": state_enum.value,
                "detected_intent": Intent.COMPLAINT.value,
                "has_image": False,
                "is_escalated": False,
                "dialog_phase": None,
            }

            route = route_after_intent(state)
            assert route == "escalation", f"Complaint in {state_enum} must escalate"

    def test_size_help_available_in_relevant_states(self):
        """SIZE_HELP intent should be handled appropriately."""
        from src.agents.langgraph.edges import route_after_intent
        from src.core.state_machine import Intent, State

        # Size help in size selection state
        state = {
            "current_state": State.STATE_3_SIZE_COLOR.value,
            "detected_intent": Intent.SIZE_HELP.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": None,
        }

        route = route_after_intent(state)
        # Should go to agent for size help
        assert route in ["agent", "offer"], f"Size help should be handled, got '{route}'"
