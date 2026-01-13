"""
Quality Evals (Phase 3).
========================
Tests intent classification accuracy on a "Golden Dataset".
This acts as a "Brain Gym" ensuring logic works not just randomly but systematically.
"""

import pytest
from src.agents.langgraph.nodes.intent import detect_intent_from_text
from src.core.state_machine import State

# Golden Dataset: (Input, Expected Intent)
DATASET = [
    ("Привіт, я хочу купити плаття", "PRODUCT_CATEGORY"),
    ("Скільки коштує?", "DISCOVERY_OR_QUESTION"),
    ("Який склад тканини?", "DISCOVERY_OR_QUESTION"),
    ("Беру, давайте реквізити", "PAYMENT_DELIVERY"),
    ("Ось чек про оплату", "PAYMENT_DELIVERY"), # Should be transactional/payment
    ("Мені не підійшов розмір, хочу повернути", "COMPLAINT"),
    ("Дякуємо, все супер!", "THANKYOU_SMALLTALK"),
]

@pytest.mark.evals
class TestIntentQuality:
    """Evaluates intent detection quality."""

    @pytest.mark.parametrize("text, expected_intent", DATASET)
    def test_intent_accuracy(self, text, expected_intent):
        """
        Verify that intent detection matches the golden standard.
        Note: This uses the heuristic/regex based detection initially,
        or calls LLM if configured. Here we test the unified router logic.
        """
        # We mock current state as INIT for generic detection
        detected = detect_intent_from_text(
            text=text,
            has_image=False,
            current_state=State.STATE_0_INIT.value
        )

        # Soft assertion (warn instead of fail if close?)
        # For now, strict check.
        # Note: "Ось чек" might depend on image flag, but text analysis should catch keywords.

        if expected_intent == "PAYMENT_DELIVERY" and "чек" in text.lower():
             # Special case: without image, might be just payment intent
             assert detected in ("PAYMENT_DELIVERY", "Payment"), f"Failed on '{text}'"
        else:
             # Basic intent mapping might differ slightly (e.g. GREETING vs DISCOVERY)
             # Allow fuzzy match if needed
             assert detected == expected_intent, f"Failed on '{text}': expected {expected_intent}, got {detected}"
