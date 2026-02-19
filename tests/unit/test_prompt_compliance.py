import pytest

from src.core.prompt_registry import PromptRegistry


# GoldenLoader imported but not used in this file - remove unused import

# Load Registry (Subject Under Test)
registry = PromptRegistry()
STATE5_PROMPT_KEYS = [
    "STATE_5_PAYMENT_DELIVERY",
    "STATE_5_PAYMENT_DELIVERY_REQUEST",
    "STATE_5_PAYMENT_DELIVERY_CONFIRM",
    "STATE_5_PAYMENT_DELIVERY_PAYMENT",
    "STATE_5_PAYMENT_DELIVERY_THANKS",
]
STATE5_PREPROOF_KEYS = [
    "STATE_5_PAYMENT_DELIVERY",
    "STATE_5_PAYMENT_DELIVERY_REQUEST",
    "STATE_5_PAYMENT_DELIVERY_CONFIRM",
    "STATE_5_PAYMENT_DELIVERY_PAYMENT",
]


class TestPromptStaticCompliance:
    """Verifies that the static prompt text contains critical business logic instructions."""

    def test_payment_template_presence(self):
        """STATE_5 must contain essential payment information."""
        prompt_content = registry.get("state.STATE_5_PAYMENT_DELIVERY").content

        # Check for essential payment elements
        assert "200 грн" in prompt_content, "Prepayment amount should be mentioned"
        assert "IBAN" in prompt_content, "Bank details should be present"
        assert "customer_data" in prompt_content, (
            "Customer data extraction instructions should be present"
        )

    def test_size_boundary_table_presence(self):
        """STATE_3 must contain the exact size mapping table text."""
        prompt_content = registry.get("state.STATE_3_SIZE_COLOR").content

        # Check for critical boundary line
        # "112-119 см (Межа!) -> 122" matches the markdown format
        assert "112-119 см (Межа!)" in prompt_content
        assert "**122**" in prompt_content

    def test_video_priority_rule(self):
        """STATE_1 must NOT contain 'VIDEO PRIORITY' as per latest user request."""
        prompt_content = registry.get("state.STATE_1_DISCOVERY").content
        assert "VIDEO PRIORITY" not in prompt_content, "Video Priority rule wasn't removed!"

    def test_white_milk_rule(self):
        """STATE_3 must contain White/Milk explanation."""
        prompt_content = registry.get("state.STATE_3_SIZE_COLOR").content
        assert "White/Milk Equivalence" in prompt_content
        assert 'ЗАБОРОНЕНО писати "білого немає' in prompt_content


class TestState5PromptCodeConsistency:
    """STATE_5 prompts should stay consistent with deterministic guards in code."""

    def test_state5_short_ack_rules_match_code_guardrails(self):
        prompt_content = registry.get("state.STATE_5_PAYMENT_DELIVERY").content.lower()

        # Prompt must explicitly keep short acknowledgements in payment flow.
        assert "так" in prompt_content
        assert "ок" in prompt_content
        assert "дякую" in prompt_content
        assert "payment_delivery" in prompt_content
        assert "залишайся в state_5" in prompt_content

    def test_state5_explicit_cancel_is_documented(self):
        from src.agents.langgraph.nodes.intent import STATE5_EXPLICIT_CANCEL_PATTERNS

        prompt_content = "\n".join(
            registry.get(f"state.{key}").content.lower() for key in STATE5_PREPROOF_KEYS
        )
        documented = [token for token in STATE5_EXPLICIT_CANCEL_PATTERNS if token in prompt_content]

        assert documented, (
            "STATE_5 prompt must document explicit cancel/refusal markers "
            "that are handled in code."
        )

    def test_state5_prompt_has_no_directive_to_finish_without_proof(self):
        prompt_content = "\n".join(
            registry.get(f"state.{key}").content.lower() for key in STATE5_PREPROOF_KEYS
        )
        contradictory_phrases = [
            "- завершуй діалог без скріну",
            "- завершуй без підтвердження оплати",
        ]
        for phrase in contradictory_phrases:
            assert phrase not in prompt_content

    @pytest.mark.parametrize("prompt_key", STATE5_PREPROOF_KEYS)
    def test_state5_preproof_prompts_require_payment_proof_before_finish(self, prompt_key):
        prompt_content = registry.get(f"state.{prompt_key}").content.lower()

        assert "не завершуй діалог" in prompt_content
        assert ("скрін" in prompt_content) or ("квитанц" in prompt_content)

    def test_state5_thanks_prompt_is_gated_by_proof(self):
        prompt_content = registry.get("state.STATE_5_PAYMENT_DELIVERY_THANKS").content.lower()

        assert "тільки після payment proof" in prompt_content
        assert "скрін" in prompt_content

    def test_state5_payment_prompt_has_single_bubble_contract(self):
        prompt_content = registry.get("state.STATE_5_PAYMENT_DELIVERY_PAYMENT").content.lower()

        assert "3 бабл" in prompt_content
        assert "4 бабл" not in prompt_content
