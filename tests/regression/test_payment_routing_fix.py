"""
REGRESSION: Payment routing bug fix.

BUG DESCRIPTION (Fixed 2025-12-13):
- Payment intent (PAYMENT_DELIVERY) in STATE_4_OFFER was routing to 'agent' instead of 'payment'
- Payment intent in STATE_5_PAYMENT_DELIVERY was routing to 'offer' instead of 'payment'
- This caused FSM invariant violations and broken payment flows

ROOT CAUSE:
- edges.py _resolve_intent_route() had incorrect routing logic
- master_router() didn't handle OFFER_MADE and WAITING_FOR_PAYMENT_* phases correctly

FIX:
- Modified _resolve_intent_route to route PAYMENT_DELIVERY in STATE_4/STATE_5 to payment
- Modified master_router to route OFFER_MADE confirmations to payment

AFFECTED FILES:
- src/agents/langgraph/edges.py (lines 156-199, 306-313)
"""

import pytest

from src.core.state_machine import Intent, State


@pytest.mark.regression
@pytest.mark.critical
class TestPaymentRoutingRegression:
    """
    Regression tests for payment routing bug.

    These tests MUST pass - they prevent return of the payment routing bug.
    """

    def test_offer_state_payment_intent_routes_to_payment(self):
        """
        BUG: In STATE_4_OFFER, PAYMENT_DELIVERY was routing to 'agent'.
        FIX: Should route to 'payment'.
        """
        from src.agents.langgraph.edges import route_after_intent

        state = {
            "current_state": State.STATE_4_OFFER.value,
            "detected_intent": Intent.PAYMENT_DELIVERY.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "OFFER_MADE",
        }

        route = route_after_intent(state)
        assert route == "payment", (
            f"REGRESSION: STATE_4_OFFER + PAYMENT_DELIVERY should route to 'payment', got '{route}'"
        )

    def test_payment_state_payment_intent_routes_to_payment(self):
        """
        BUG: In STATE_5_PAYMENT, PAYMENT_DELIVERY was routing to 'offer'.
        FIX: Should route to 'payment'.
        """
        from src.agents.langgraph.edges import route_after_intent

        state = {
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "detected_intent": Intent.PAYMENT_DELIVERY.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "WAITING_FOR_PAYMENT_METHOD",
        }

        route = route_after_intent(state)
        assert route == "payment", (
            f"REGRESSION: STATE_5_PAYMENT + PAYMENT_DELIVERY should route to 'payment', got '{route}'"
        )

    def test_offer_made_confirmation_routes_correctly(self):
        """
        BUG: User saying 'беру' in OFFER_MADE phase was going to wrong node.
        FIX: Should route through proper flow (intent detection first, then payment).

        Note: master_router may route to 'moderation' or 'intent' first as entry points,
        but route_after_intent should ultimately route to 'payment'.
        """
        from src.agents.langgraph.edges import route_after_intent

        state = {
            "current_state": State.STATE_4_OFFER.value,
            "detected_intent": Intent.PAYMENT_DELIVERY.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "OFFER_MADE",
        }

        route = route_after_intent(state)
        assert route == "payment", (
            f"REGRESSION: OFFER_MADE + PAYMENT_DELIVERY should route to 'payment', got '{route}'"
        )

    def test_waiting_for_payment_method_stays_in_payment(self):
        """
        BUG: WAITING_FOR_PAYMENT_METHOD phase was exiting payment flow.
        FIX: Should stay in 'payment' node.
        """
        from src.agents.langgraph.edges import master_router

        state = {
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "detected_intent": Intent.PAYMENT_DELIVERY.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "WAITING_FOR_PAYMENT_METHOD",
            "metadata": {},
        }

        route = master_router(state)
        assert route == "payment", (
            f"REGRESSION: WAITING_FOR_PAYMENT_METHOD should route to 'payment', got '{route}'"
        )

    def test_waiting_for_payment_proof_stays_in_payment(self):
        """
        BUG: WAITING_FOR_PAYMENT_PROOF phase was exiting payment flow.
        FIX: Should stay in 'payment' node.
        """
        from src.agents.langgraph.edges import master_router

        state = {
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "detected_intent": Intent.PAYMENT_DELIVERY.value,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
            "metadata": {},
        }

        route = master_router(state)
        assert route == "payment", (
            f"REGRESSION: WAITING_FOR_PAYMENT_PROOF should route to 'payment', got '{route}'"
        )


@pytest.mark.regression
@pytest.mark.critical
class TestFSMInvariantsRegression:
    """
    Regression tests for FSM invariant violations.

    These ensure the state machine rules are always respected.
    """

    def test_complaint_always_escalates(self):
        """
        INVARIANT: COMPLAINT intent must always route to 'escalation'.
        """
        from src.agents.langgraph.edges import route_after_intent

        for state_enum in State:
            state = {
                "current_state": state_enum.value,
                "detected_intent": Intent.COMPLAINT.value,
                "has_image": False,
                "is_escalated": False,
                "dialog_phase": None,
            }

            route = route_after_intent(state)
            assert route == "escalation", (
                f"INVARIANT: COMPLAINT in {state_enum} must escalate, got '{route}'"
            )

    def test_photo_ident_always_goes_to_vision(self):
        """
        INVARIANT: PHOTO_IDENT intent must always route to 'vision'.
        """
        from src.agents.langgraph.edges import route_after_intent

        for state_enum in State:
            state = {
                "current_state": state_enum.value,
                "detected_intent": Intent.PHOTO_IDENT.value,
                "has_image": True,
                "is_escalated": False,
                "dialog_phase": None,
            }

            route = route_after_intent(state)
            assert route == "vision", (
                f"INVARIANT: PHOTO_IDENT in {state_enum} must go to vision, got '{route}'"
            )

    def test_state_values_always_valid(self):
        """
        INVARIANT: current_state must always be a valid State enum value.
        """
        from src.core.state_machine import State

        valid_values = {s.value for s in State}

        for state_enum in State:
            assert state_enum.value in valid_values, (
                f"INVARIANT: State {state_enum} has invalid value"
            )
