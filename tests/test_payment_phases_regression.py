"""
Regression Tests: Payment Phase Transitions.
===========================================
Tests that payment phases align with UX and prompts correctly.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
root = Path(__file__).resolve().parents[1]
project_root = str(root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.langgraph.state import create_initial_state
from src.agents.langgraph.state_prompts import determine_next_dialog_phase, get_payment_sub_phase
from src.core.state_machine import State


class TestPaymentPhaseRegression:
    """Regression tests for payment phase transitions."""

    def test_offer_asks_delivery_data_phase_is_waiting_for_delivery(self):
        """When offer response asks for delivery data, phase must be WAITING_FOR_DELIVERY_DATA."""
        # Simulate offer response that asks for delivery data
        current_state = State.STATE_4_OFFER.value
        intent = "PAYMENT_DELIVERY"
        has_products = True
        has_size = True
        has_color = True
        user_confirmed = True
        
        phase = determine_next_dialog_phase(
            current_state=current_state,
            intent=intent,
            has_products=has_products,
            has_size=has_size,
            has_color=has_color,
            user_confirmed=user_confirmed,
        )
        
        assert phase == "WAITING_FOR_DELIVERY_DATA", (
            f"Offer with PAYMENT_DELIVERY intent should transition to WAITING_FOR_DELIVERY_DATA, "
            f"got {phase}"
        )

    def test_payment_subphase_oplatila_maps_to_waiting_for_proof(self):
        """When user says 'Оплатила', sub-phase should be SHOW_PAYMENT → WAITING_FOR_PAYMENT_PROOF."""
        state = create_initial_state(
            session_id="test_oplatila",
            messages=[{"role": "user", "content": "Оплатила"}],
            metadata={"channel": "instagram"},
        )
        state["current_state"] = State.STATE_5_PAYMENT_DELIVERY.value
        state["dialog_phase"] = "WAITING_FOR_PAYMENT_METHOD"
        
        # Get payment sub-phase (should detect "оплатила" keyword)
        sub_phase = get_payment_sub_phase(state)
        
        assert sub_phase == "SHOW_PAYMENT", (
            f"User message 'Оплатила' should map to SHOW_PAYMENT sub-phase, got {sub_phase}"
        )
        
        # Map sub-phase to dialog_phase
        phase = determine_next_dialog_phase(
            current_state=State.STATE_5_PAYMENT_DELIVERY.value,
            intent="PAYMENT_DELIVERY",
            has_products=True,
            has_size=True,
            has_color=True,
            user_confirmed=True,
            payment_sub_phase=sub_phase,
        )
        
        assert phase == "WAITING_FOR_PAYMENT_PROOF", (
            f"SHOW_PAYMENT sub-phase should map to WAITING_FOR_PAYMENT_PROOF phase, got {phase}"
        )

    def test_payment_subphase_delivery_data_maps_to_waiting_for_delivery(self):
        """When user provides delivery data, sub-phase should be CONFIRM_DATA → WAITING_FOR_PAYMENT_METHOD."""
        state = create_initial_state(
            session_id="test_delivery_data",
            messages=[
                {"role": "user", "content": "Іван Іванович Іванов\n+380951234567\nКиїв, відділення 54"}
            ],
            metadata={"channel": "instagram"},
        )
        state["current_state"] = State.STATE_5_PAYMENT_DELIVERY.value
        state["dialog_phase"] = "WAITING_FOR_DELIVERY_DATA"
        # Simulate extracted customer data
        state["metadata"]["customer_name"] = "Іван Іванович Іванов"
        state["metadata"]["customer_phone"] = "+380951234567"
        state["metadata"]["customer_city"] = "Київ"
        state["metadata"]["customer_nova_poshta"] = "відділення 54"
        
        sub_phase = get_payment_sub_phase(state)
        
        assert sub_phase == "CONFIRM_DATA", (
            f"State with delivery data should map to CONFIRM_DATA sub-phase, got {sub_phase}"
        )
        
        phase = determine_next_dialog_phase(
            current_state=State.STATE_5_PAYMENT_DELIVERY.value,
            intent="PAYMENT_DELIVERY",
            has_products=True,
            has_size=True,
            has_color=True,
            user_confirmed=True,
            payment_sub_phase=sub_phase,
        )
        
        assert phase == "WAITING_FOR_PAYMENT_METHOD", (
            f"CONFIRM_DATA sub-phase should map to WAITING_FOR_PAYMENT_METHOD phase, got {phase}"
        )

    def test_payment_phase_consistency_offer_to_delivery(self):
        """Test full flow: OFFER_MADE → (user confirms) → WAITING_FOR_DELIVERY_DATA."""
        # Step 1: Offer made
        state_offer = {
            "current_state": State.STATE_4_OFFER.value,
            "dialog_phase": "OFFER_MADE",
            "selected_products": [{"name": "Сукня Анна", "size": "146-152", "color": "голубий"}],
        }
        
        # Step 2: User confirms ("беру")
        phase_after_confirmation = determine_next_dialog_phase(
            current_state=State.STATE_4_OFFER.value,
            intent="PAYMENT_DELIVERY",
            has_products=True,
            has_size=True,
            has_color=True,
            user_confirmed=True,
        )
        
        assert phase_after_confirmation == "WAITING_FOR_DELIVERY_DATA", (
            f"After confirmation in OFFER_MADE, phase should be WAITING_FOR_DELIVERY_DATA, "
            f"got {phase_after_confirmation}"
        )

    def test_payment_method_selection_not_treated_as_proof(self):
        """
        Regression test for log issue: "Повна оплата" after payment method question
        should be treated as method selection, NOT as delivery/proof.
        
        Scenario from log:
        - Bot asks: "Як вам зручніше оплатити: повна оплата 1885 грн чи передплата 200 грн?"
        - User responds: "Повна оплата"
        - Expected: WAITING_FOR_PAYMENT_METHOD → process as method selection → show requisites
        - Bug: Was treated as WAITING_FOR_PAYMENT_PROOF → wrong handler → wrong response
        """
        # Simulate state after bot asked payment method question
        state = create_initial_state(
            session_id="test_payment_method_selection",
            messages=[
                {"role": "assistant", "content": "Як вам зручніше оплатити: повна оплата 1885 грн чи передплата 200 грн?"},
                {"role": "user", "content": "Повна оплата"},
            ],
            metadata={
                "channel": "instagram",
                # All delivery data collected
                "customer_name": "Іван Іванович",
                "customer_phone": "+380951234567",
                "customer_city": "Київ",
                "customer_nova_poshta": "54",
            },
        )
        state["current_state"] = State.STATE_5_PAYMENT_DELIVERY.value
        state["dialog_phase"] = "WAITING_FOR_PAYMENT_METHOD"  # Bot asked method question
        state["selected_products"] = [{"name": "Костюм Каприз", "price": 1885.0}]
        
        # Get payment sub-phase - should detect that we have data but no payment method selected yet
        sub_phase = get_payment_sub_phase(state)
        
        # With all delivery data but user just selected method, we should be in CONFIRM_DATA or moving to SHOW_PAYMENT
        # But the key is: dialog_phase should remain WAITING_FOR_PAYMENT_METHOD until requisites are shown
        assert sub_phase in ("CONFIRM_DATA", "SHOW_PAYMENT"), (
            f"After selecting payment method with all data, sub-phase should be CONFIRM_DATA or SHOW_PAYMENT, "
            f"got {sub_phase}"
        )
        
        # Critical: dialog_phase should NOT be WAITING_FOR_PAYMENT_PROOF until requisites are actually shown
        # This is the bug we're fixing - payment_node was setting WAITING_FOR_PAYMENT_PROOF too early
        phase = determine_next_dialog_phase(
            current_state=State.STATE_5_PAYMENT_DELIVERY.value,
            intent="PAYMENT_DELIVERY",
            has_products=True,
            has_size=True,
            has_color=True,
            user_confirmed=True,
            payment_sub_phase=sub_phase,
        )
        
        # If sub-phase is CONFIRM_DATA, phase should be WAITING_FOR_PAYMENT_METHOD
        # If sub-phase is SHOW_PAYMENT (requisites shown), phase should be WAITING_FOR_PAYMENT_PROOF
        if sub_phase == "CONFIRM_DATA":
            assert phase == "WAITING_FOR_PAYMENT_METHOD", (
                f"When sub-phase is CONFIRM_DATA (method selected, requisites not shown yet), "
                f"dialog_phase should be WAITING_FOR_PAYMENT_METHOD, got {phase}"
            )
        elif sub_phase == "SHOW_PAYMENT":
            assert phase == "WAITING_FOR_PAYMENT_PROOF", (
                f"When sub-phase is SHOW_PAYMENT (requisites shown), "
                f"dialog_phase should be WAITING_FOR_PAYMENT_PROOF, got {phase}"
            )

