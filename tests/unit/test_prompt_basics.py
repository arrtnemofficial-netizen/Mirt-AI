"""Tests for system prompt validation and structure (Markdown-based).

These tests verify:
1. System prompt file exists
2. Required sections exist (Identity, Rules)
3. Content quality (Ukrainian, No placeholders)
"""

from pathlib import Path
import pytest
from src.core.prompt_registry import PromptRegistry

# Load Registry
registry = PromptRegistry()

class TestSystemPromptBasics:
    """Test system/main.md content."""

    @pytest.fixture
    def prompt_content(self) -> str:
        """Get system prompt content from registry."""
        return registry.get("system.main").content

    def test_has_identity_section(self, prompt_content):
        """Prompt should define AI identity."""
        assert "# Роль" in prompt_content or "IDENTITY" in prompt_content
        assert "Софія" in prompt_content
        assert "MIRT" in prompt_content

    def test_has_do_and_do_not(self, prompt_content):
        """Prompt should have DO and DO NOT sections."""
        assert "## DO" in prompt_content
        assert "## DO NOT" in prompt_content

    def test_has_escalation_rules(self, prompt_content):
        """Prompt should mention escalation or safety."""
        # Use lower case check or partial match for Ukrainian header
        assert "escalation" in prompt_content.lower() or "безпека" in prompt_content.lower()
        assert "EXIT" in prompt_content

    def test_no_placeholder_text(self, prompt_content):
        """Prompt should not have placeholder text."""
        placeholders = ["TODO", "FIXME", "XXX", "PLACEHOLDER", "YOUR_NAME"]
        for ph in placeholders:
            assert ph not in prompt_content, f"Found placeholder: {ph}"

    def test_has_ukrainian_content(self, prompt_content):
        """Prompt should have Ukrainian language content."""
        ukrainian_words = ["привіт", "дякую", "будь ласка", "замовлення", "вітаю"]
        found = any(word in prompt_content.lower() for word in ukrainian_words)
        assert found, "Prompt should contain Ukrainian content"

    def test_formatting_markdown(self, prompt_content):
        """Prompt should use markdown headers."""
        assert "# " in prompt_content

class TestStatePromptsBasics:
    """Test reliability of state prompts."""

    def test_all_states_loadable(self):
        """All critical states should load without error."""
        states = [
            "STATE_0_INIT",
            "STATE_1_DISCOVERY",
            "STATE_2_VISION",
            "STATE_3_SIZE_COLOR",
            "STATE_4_OFFER",
            "STATE_5_PAYMENT_DELIVERY",
            "STATE_6_UPSELL",
            "STATE_7_END",
            "STATE_8_COMPLAINT",
            "STATE_9_OOD",
        ]
        for state in states:
            content = registry.get(f"state.{state}").content
            assert len(content) > 10, f"State {state} is empty"
            assert "## DO" in content, f"State {state} missing DO section"

    def test_all_states_from_enum_have_prompts(self):
        """Every state in State enum must have a prompt file."""
        from src.core.prompt_registry import validate_all_states_have_prompts
        missing = validate_all_states_have_prompts()
        assert not missing, f"Missing prompt files for states: {missing}"

    def test_state_prompts_have_transitions(self):
        """State prompts should document transitions."""
        from src.core.state_machine import State
        for state in State:
            content = registry.get(f"state.{state.value}").content
            assert "## TRANSITIONS" in content, f"{state.value} missing TRANSITIONS section"

    def test_state_prompts_have_examples(self):
        """State prompts should have examples."""
        from src.core.state_machine import State
        for state in State:
            content = registry.get(f"state.{state.value}").content
            assert "## EXAMPLES" in content, f"{state.value} missing EXAMPLES section"
