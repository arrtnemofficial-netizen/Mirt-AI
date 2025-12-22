"""Tests for system prompt validation and structure.

These tests verify the modular prompt system managed by PromptRegistry.
"""

import pytest
import yaml
from src.core.prompt_registry import registry
from src.core.registry_keys import SystemKeys


@pytest.fixture
def combined_prompt_content() -> str:
    """Load and combine core system prompts for aggregate validation."""
    from src.core.registry_keys import DomainKeys
    
    components = [
        SystemKeys.BASE_IDENTITY,
        SystemKeys.MAIN_AGENT,
        DomainKeys.MAIN_MAIN,  # main.md contains escalation rules
        SystemKeys.INTENTS,
        SystemKeys.FALLBACKS,
        "system.payment",
    ]
    content = ""
    for key_raw in components:
        key = str(getattr(key_raw, "value", key_raw))
        try:
            content += f"\n\n# --- {key} ---\n\n"
            content += registry.get(key).content
        except Exception:
            # Payment might be missing in some branches, allow it
            if key != "system.payment":
                pytest.fail(f"Failed to load prompt component {key}")
    return content


class TestPromptSyntax:
    """Test prompt file syntax and existence."""

    def test_registry_health(self):
        """Registry should resolve all critical keys."""
        critical_keys = [
            SystemKeys.BASE_IDENTITY,
            SystemKeys.MAIN_AGENT,
            SystemKeys.INTENTS,
            SystemKeys.FALLBACKS,
            SystemKeys.STATE_MACHINE,
        ]
        for key in critical_keys:
            config = registry.get(key)
            assert config.content, f"Prompt content for {key} is empty"
            assert config.path.exists(), f"Prompt file for {key} does not exist at {config.path}"

    def test_state_machine_yaml_is_valid(self):
        """State machine config should be valid YAML."""
        content = registry.get(SystemKeys.STATE_MACHINE).content
        try:
            data = yaml.safe_load(content)
            assert isinstance(data, dict), "State machine config must be a dictionary"
            assert "state_labels" in data
        except yaml.YAMLError as e:
            pytest.fail(f"Invalid YAML in state_machine.yaml: {e}")


class TestPromptStructure:
    """Test required prompt sections across modular prompts."""

    def test_has_identity_section(self, combined_prompt_content):
        """Prompt should define AI identity (Sofia)."""
        # We moved from 'IDENTITY' header to markdown hierarchy
        assert "Софія" in combined_prompt_content
        assert "MIRT_UA" in combined_prompt_content or "МІРТ" in combined_prompt_content

    def test_has_state_machine_mentions(self, combined_prompt_content):
        """Prompt should mention key states for LLM awareness."""
        required_states = [
            "STATE_0_INIT",
            "STATE_1_DISCOVERY",
            "STATE_4_OFFER",
            "STATE_5_PAYMENT_DELIVERY",
            "STATE_7_END",
        ]
        for state in required_states:
            assert state in combined_prompt_content, f"Missing state mention: {state}"

    def test_has_intent_classification(self, combined_prompt_content):
        """Prompt should define intent patterns (now in intents.md)."""
        required_keywords = [
            "купую",
            "так",
            "костюм",
        ]
        for word in required_keywords:
            assert word.lower() in combined_prompt_content.lower(), f"Missing keyword pattern: {word}"

    def test_has_escalation_rules(self, combined_prompt_content):
        """Prompt should define escalation levels."""
        assert "L1" in combined_prompt_content
        assert "L2" in combined_prompt_content
        assert "ESCALATION" in combined_prompt_content.upper()

    def test_has_ukrainian_content(self, combined_prompt_content):
        """Prompt should have Ukrainian language content."""
        ukrainian_words = ["привіт", "дякую", "будь ласка", "замовлення", "доставка"]
        found = any(word in combined_prompt_content.lower() for word in ukrainian_words)
        assert found, "Prompt should contain Ukrainian content"


class TestPromptRules:
    """Test business rules in prompt."""

    def test_identity_protection(self, combined_prompt_content):
        """AI should never admit to being a bot, should act as Sofia."""
        assert "Софія" in combined_prompt_content
        assert "менеджер" in combined_prompt_content.lower()

    def test_has_payment_methods(self, combined_prompt_content):
        """Prompt should define payment methods."""
        payment_terms = ["передплат", "оплат", "200 грн", "на карт"]
        found = sum(1 for term in payment_terms if term.lower() in combined_prompt_content.lower())
        assert found >= 1, "Prompt should mention payment options"

    def test_has_delivery_info(self, combined_prompt_content):
        """Prompt should mention delivery."""
        delivery_terms = ["нова пошта", "доставк", "відділен"]
        found = any(term in combined_prompt_content.lower() for term in delivery_terms)
        assert found, "Prompt should mention delivery options"
