
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from src.core.state_machine import State
from src.conf.payment_config import PAYMENT_PREPAY_AMOUNT

# =============================================================================
# TEST 1: PROMPT REGISTRY INJECTION (SSOT)
# =============================================================================

def test_prompt_registry_injects_prepay_amount():
    """
    Verify that PromptRegistry replaces {PAYMENT_PREPAY_AMOUNT} with the config value.
    This ensures that fixing the '200 грн' hardcoded value works as expected.
    """
    from src.core.prompt_registry import registry
    
    # Mock file content with placeholder
    mock_content = "Please pay {PAYMENT_PREPAY_AMOUNT} UAH now."
    
    # We patch _load_file to return our mock content
    with patch.object(registry, '_load_file', return_value=mock_content.replace("{PAYMENT_PREPAY_AMOUNT}", str(PAYMENT_PREPAY_AMOUNT))):
        # Note: In our implementation, _load_file DOES the replacement. 
        # So we should actually test _load_file specifically or mock open().
        pass

    # Better approach: Test _load_file logic directly by mocking open()
    with patch("builtins.open", new_callable=MagicMock) as mock_open:
        mock_file = MagicMock()
        mock_file.__enter__.return_value.read.return_value = "Please pay {PAYMENT_PREPAY_AMOUNT} UAH now."
        mock_open.return_value = mock_file
        
        # Call valid private method to test logic or public get() with a mocked path
        # Since we can't easily inject a fake file path that exists() for get(),
        # we'll test the logic by instantiating registry and calling _load_file on a dummy path
        
        result = registry._load_file(Path("dummy.md"))
        
        # ASSERTION: Placeholder must be replaced by actual value
        expected_amount = str(PAYMENT_PREPAY_AMOUNT)
        assert expected_amount in result
        assert "{PAYMENT_PREPAY_AMOUNT}" not in result
        assert f"Please pay {expected_amount} UAH now." == result

# =============================================================================
# TEST 2: TRANSITION LOGIC (SSOT)
# =============================================================================

def test_derive_dialog_phase_payment_flow():
    """
    Verify that transition_reducer.derive_dialog_phase correctly handles payment sub-phases.
    This logic was moved from state_prompts.py.
    """
    from src.agents.langgraph.fsm.transition_reducer import derive_dialog_phase
    
    # Case 1: PAYMENT_DELIVERY with REQUEST_DATA
    phase = derive_dialog_phase(
        current_state="STATE_5_PAYMENT_DELIVERY",
        intent="PAYMENT_DELIVERY",
        has_products=True,
        has_size=True,
        has_color=True,
        user_confirmed=False,
        payment_sub_phase="REQUEST_DATA"
    )
    assert phase == "WAITING_FOR_DELIVERY_DATA"
    
    # Case 2: PAYMENT_DELIVERY with CONFIRM_DATA
    phase = derive_dialog_phase(
        current_state="STATE_5_PAYMENT_DELIVERY",
        intent="PAYMENT_DELIVERY",
        has_products=True, 
        has_size=True,
        has_color=True,
        user_confirmed=False,
        payment_sub_phase="CONFIRM_DATA"
    )
    assert phase == "WAITING_FOR_PAYMENT_METHOD"

    # Case 3: PAYMENT_DELIVERY with SHOW_PAYMENT
    phase = derive_dialog_phase(
        current_state="STATE_5_PAYMENT_DELIVERY",
        intent="PAYMENT_DELIVERY",
        has_products=True,
        has_size=True,
        has_color=True,
        user_confirmed=False,
        payment_sub_phase="SHOW_PAYMENT"
    )
    assert phase == "WAITING_FOR_PAYMENT_PROOF"

def test_derive_dialog_phase_offer_transition():
    """Verify OFFER -> PAYMENT transition logic."""
    from src.agents.langgraph.fsm.transition_reducer import derive_dialog_phase
    
    # User says "беру" (user_confirmed=True) in STATE_4
    phase = derive_dialog_phase(
        current_state="STATE_4_OFFER",
        intent="PAYMENT_DELIVERY", # or any intent really if user_confirmed is True
        has_products=True,
        has_size=True,
        has_color=True,
        user_confirmed=True,
        payment_sub_phase=None
    )
    assert phase == "WAITING_FOR_DELIVERY_DATA"

# =============================================================================
# TEST 3: INTENT DETECTION (SSOT)
# =============================================================================

def test_unified_intent_detection():
    """
    Verify that nodes.intent.detect_intent_from_text handles keywords correctly.
    This replaces the removed detect_simple_intent from state_prompts.py.
    """
    from src.agents.langgraph.nodes.intent import detect_intent_from_text
    
    # Test "беру" -> PAYMENT_DELIVERY
    intent = detect_intent_from_text("я беру це", has_image=False, current_state="STATE_4_OFFER")
    assert intent == "PAYMENT_DELIVERY"
    
    # Test "розмір" -> SIZE_HELP
    intent = detect_intent_from_text("який розмір краще?", has_image=False, current_state="STATE_1_DISCOVERY")
    assert intent == "SIZE_HELP"
    
    # Test "покажи фото" -> REQUEST_PHOTO
    intent = detect_intent_from_text("можна реальне фото?", has_image=False, current_state="STATE_1_DISCOVERY")
    assert intent == "REQUEST_PHOTO"

if __name__ == "__main__":
    # Allow running directly
    pytest.main([__file__])
