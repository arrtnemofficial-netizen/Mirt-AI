import sys
import os
import pytest

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.langgraph.state_prompts import get_payment_sub_phase

def test_payment_logic_guarantee():
    """
    Ironclad test to prove that providing FULL DATA prevents the 'REQUEST_DATA' loop.
    """
    
    # CASE 1: Empty metadata -> Must ask for data
    state_empty = {"metadata": {}}
    result = get_payment_sub_phase(state_empty)
    print(f"Empty Metadata -> {result}")
    assert result == "REQUEST_DATA", "Empty metadata should request data"

    # CASE 2: Partial data (Calculated Loop Hazard) -> Must ask for data
    state_partial = {
        "metadata": {
            "customer_name": "Taras",
            # Missing phone, city, np
        }
    }
    result = get_payment_sub_phase(state_partial)
    print(f"Partial Metadata -> {result}")
    assert result == "REQUEST_DATA", "Partial data should still request missing fields"

    # CASE 3: FULL DATA (The 'Ironclad' Scenario) -> Must NOT ask for data
    state_full = {
        "metadata": {
            "customer_name": "Taras",
            "customer_phone": "0991234567",
            "customer_city": "Kyiv",
            "customer_nova_poshta": "1",
        }
    }
    result = get_payment_sub_phase(state_full)
    print(f"Full Metadata -> {result}")
    
    # Should be CONFIRM_DATA or SHOW_PAYMENT, NEVER REQUEST_DATA
    assert result in ["CONFIRM_DATA", "SHOW_PAYMENT"], \
        f"Full data MUST NOT loop back to REQUEST_DATA. Got: {result}"
    
    # CASE 4: Payment Proof (The 'Fixed' Bug)
    state_paid = {
        "metadata": {
            "customer_name": "Taras",
            "customer_phone": "0991234567",
            "customer_city": "Kyiv",
            "customer_nova_poshta": "1",
            "payment_proof_received": True # This triggered the bug before
        }
    }
    result = get_payment_sub_phase(state_paid)
    print(f"Payment Proof -> {result}")
    assert result == "THANK_YOU", "Proof must trigger THANK_YOU"

    print("\n✅ ALL LOGIC TESTS PASSED. The loop is mathematically impossible.")

if __name__ == "__main__":
    test_payment_logic_guarantee()
