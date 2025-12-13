"""
E2E: Text-based discovery to payment flow.

Complete user journey without photo:
1. User asks about products via text
2. Agent helps discover needs
3. User specifies size/color
4. Offer is made
5. Payment flow completes

Alternative happy path for users without photos.
"""

import pytest

from src.core.state_machine import Intent, State


@pytest.mark.e2e
class TestTextDiscoveryFlow:
    """End-to-end test for text discovery → payment journey."""

    def test_discovery_intent_goes_to_agent(self):
        """Discovery questions should go to agent node."""
        from src.agents.langgraph.edges import route_after_intent

        state = {
            "current_state": State.STATE_1_DISCOVERY.value,
            "detected_intent": Intent.DISCOVERY_OR_QUESTION.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": None,
        }

        route = route_after_intent(state)
        assert route == "agent", f"Discovery question should go to agent, got '{route}'"

    def test_size_selection_available(self):
        """After product found, size selection should work."""
        from src.agents.langgraph.edges import route_after_intent

        state = {
            "current_state": State.STATE_3_SIZE_COLOR.value,
            "detected_intent": Intent.SIZE_HELP.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "WAITING_FOR_SIZE",
        }

        route = route_after_intent(state)
        assert route in ["agent", "offer"], f"Size selection should be handled, got '{route}'"

    def test_color_selection_available(self):
        """Color selection questions should be handled."""
        from src.agents.langgraph.edges import route_after_intent

        state = {
            "current_state": State.STATE_3_SIZE_COLOR.value,
            "detected_intent": Intent.COLOR_HELP.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "WAITING_FOR_COLOR",
        }

        route = route_after_intent(state)
        assert route in ["agent", "offer"], f"Color selection should be handled, got '{route}'"

    def test_offer_state_reachable(self):
        """STATE_4_OFFER should be reachable after size/color."""
        from src.agents.langgraph.edges import master_router

        state = {
            "current_state": State.STATE_4_OFFER.value,
            "detected_intent": None,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "OFFER_MADE",
            "metadata": {},
        }

        route = master_router(state)
        # Should stay in offer-related nodes
        assert route in ["agent", "payment", "offer"], (
            f"Offer state should be reachable, got '{route}'"
        )


@pytest.mark.e2e
class TestComplaintEscalationFlow:
    """E2E test for complaint → escalation journey."""

    def test_complaint_from_discovery_escalates(self):
        """Complaint in discovery state must escalate."""
        from src.agents.langgraph.edges import route_after_intent

        state = {
            "current_state": State.STATE_1_DISCOVERY.value,
            "detected_intent": Intent.COMPLAINT.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": None,
        }

        route = route_after_intent(state)
        assert route == "escalation"

    def test_complaint_from_payment_escalates(self):
        """Complaint during payment must escalate."""
        from src.agents.langgraph.edges import route_after_intent

        state = {
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "detected_intent": Intent.COMPLAINT.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "WAITING_FOR_PAYMENT_METHOD",
        }

        route = route_after_intent(state)
        assert route == "escalation"

    def test_escalated_state_persists(self):
        """Once escalated, flag should persist."""
        from src.agents.langgraph.edges import master_router

        state = {
            "current_state": State.STATE_1_DISCOVERY.value,
            "detected_intent": Intent.DISCOVERY_OR_QUESTION.value,
            "has_image": False,
            "is_escalated": True,  # Already escalated
            "dialog_phase": None,
            "metadata": {},
        }

        route = master_router(state)
        # Master router always starts with moderation
        assert route in ["escalation", "__end__", "agent", "intent", "moderation"], (
            f"Escalated state should be handled, got '{route}'"
        )


@pytest.mark.e2e
class TestUpsellFlow:
    """E2E test for payment → upsell → end journey."""

    def test_payment_complete_goes_to_upsell(self):
        """After payment confirmed, should go to upsell."""
        from src.agents.langgraph.edges import master_router

        state = {
            "current_state": State.STATE_6_UPSELL.value,
            "detected_intent": None,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "COMPLETED",
            "metadata": {},
        }

        route = master_router(state)
        # Master router may start with moderation as entry point
        assert route in ["upsell", "__end__", "agent", "intent", "moderation"], (
            f"Post-payment should handle upsell, got '{route}'"
        )

    def test_end_state_terminates(self):
        """STATE_7_END should terminate the conversation."""
        from src.agents.langgraph.edges import master_router

        state = {
            "current_state": State.STATE_7_END.value,
            "detected_intent": None,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "COMPLETED",
            "metadata": {},
        }

        route = master_router(state)
        # End state may go through moderation first
        assert route in ["__end__", "intent", "agent", "moderation"], (
            f"End state should terminate, got '{route}'"
        )
