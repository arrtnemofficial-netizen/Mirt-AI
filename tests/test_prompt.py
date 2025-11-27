"""Tests for system prompt validation and structure.

These tests verify:
1. YAML syntax is valid
2. Required sections exist
3. State machine is complete
4. Intent labels are defined
"""
import pytest
import yaml
from pathlib import Path


PROMPT_PATH = Path(__file__).parent.parent / "data" / "system_prompt_full.yaml"


@pytest.fixture
def prompt_content() -> str:
    """Load raw prompt content."""
    return PROMPT_PATH.read_text(encoding="utf-8")


@pytest.fixture
def prompt_data(prompt_content: str) -> dict:
    """Parse prompt as YAML."""
    return yaml.safe_load(prompt_content)


class TestPromptSyntax:
    """Test prompt file syntax."""

    def test_yaml_is_valid(self, prompt_content):
        """YAML should parse without errors."""
        try:
            yaml.safe_load(prompt_content)
        except yaml.YAMLError as e:
            pytest.fail(f"Invalid YAML syntax: {e}")

    def test_file_exists(self):
        """Prompt file should exist."""
        assert PROMPT_PATH.exists(), f"Prompt file not found: {PROMPT_PATH}"

    def test_file_not_empty(self, prompt_content):
        """Prompt should have content."""
        assert len(prompt_content) > 1000, "Prompt seems too short"


class TestPromptStructure:
    """Test required prompt sections."""

    def test_has_identity_section(self, prompt_content):
        """Prompt should define AI identity."""
        assert "IDENTITY" in prompt_content or "Ольга" in prompt_content

    def test_has_state_machine(self, prompt_content):
        """Prompt should define state machine."""
        required_states = [
            "STATE_0_INIT",
            "STATE_1_DISCOVERY",
            "STATE_4_OFFER",
            "STATE_5_PAYMENT",
            "STATE_7_END",
        ]
        for state in required_states:
            assert state in prompt_content, f"Missing state: {state}"

    def test_has_intent_classification(self, prompt_content):
        """Prompt should define intent labels."""
        required_intents = [
            "GREETING_ONLY",
            "DISCOVERY_OR_QUESTION",
            "PAYMENT_DELIVERY",
        ]
        for intent in required_intents:
            assert intent in prompt_content, f"Missing intent: {intent}"

    def test_has_escalation_rules(self, prompt_content):
        """Prompt should define escalation levels."""
        assert "L1" in prompt_content
        assert "L2" in prompt_content
        assert "ESCALATION" in prompt_content.upper()

    def test_has_size_mapping(self, prompt_content):
        """Prompt should have size guide."""
        # Check for height ranges
        assert "122" in prompt_content or "128" in prompt_content
        assert "розмір" in prompt_content.lower() or "size" in prompt_content.lower()

    def test_has_off_topic_handling(self, prompt_content):
        """Prompt should handle off-topic messages."""
        assert "ОФТОПІК" in prompt_content.upper() or "OFF_TOPIC" in prompt_content.upper() or "CONVERSATION_RECOVERY" in prompt_content


class TestPromptContent:
    """Test prompt content quality."""

    def test_no_placeholder_text(self, prompt_content):
        """Prompt should not have placeholder text."""
        placeholders = ["TODO", "FIXME", "XXX", "PLACEHOLDER", "YOUR_"]
        for ph in placeholders:
            assert ph not in prompt_content.upper(), f"Found placeholder: {ph}"

    def test_has_ukrainian_content(self, prompt_content):
        """Prompt should have Ukrainian language content."""
        ukrainian_words = ["привіт", "дякую", "будь ласка", "замовлення", "доставка"]
        found = any(word in prompt_content.lower() for word in ukrainian_words)
        assert found, "Prompt should contain Ukrainian content"

    def test_brand_name_present(self, prompt_content):
        """Prompt should mention MIRT brand."""
        assert "MIRT" in prompt_content.upper() or "МІРТ" in prompt_content.upper()

    def test_no_hardcoded_prices(self, prompt_content):
        """Prompt should not have hardcoded prices (should come from catalog)."""
        # Allow some price examples but not too many
        import re
        price_pattern = r'\d{3,4}\s*грн'
        matches = re.findall(price_pattern, prompt_content)
        assert len(matches) < 20, f"Too many hardcoded prices: {len(matches)}"


class TestPromptRules:
    """Test business rules in prompt."""

    def test_identity_protection(self, prompt_content):
        """AI should never admit to being a bot."""
        identity_rules = [
            "людина" in prompt_content.lower() or "human" in prompt_content.lower(),
            "менеджер" in prompt_content.lower(),
        ]
        assert any(identity_rules), "Prompt should enforce human identity"

    def test_has_payment_methods(self, prompt_content):
        """Prompt should define payment methods."""
        payment_terms = ["передплата", "оплата", "200 грн", "повна"]
        found = sum(1 for term in payment_terms if term.lower() in prompt_content.lower())
        assert found >= 2, "Prompt should mention payment options"

    def test_has_delivery_info(self, prompt_content):
        """Prompt should mention delivery."""
        delivery_terms = ["нова пошта", "доставка", "відділення"]
        found = any(term in prompt_content.lower() for term in delivery_terms)
        assert found, "Prompt should mention delivery options"
