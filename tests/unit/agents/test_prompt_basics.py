"""Tests for prompt validation and structure."""

import pytest

from src.core.prompt_registry import PromptRegistry


registry = PromptRegistry()


class TestSystemPromptBasics:
    """Test base identity and main prompt content."""

    @pytest.fixture
    def base_identity_content(self) -> str:
        """Get base identity prompt content from registry."""
        return registry.get("system.base_identity").content

    @pytest.fixture
    def main_prompt_content(self) -> str:
        """Get main domain prompt content from registry."""
        return registry.get("main.main").content

    def test_base_identity_has_identity_section(self, base_identity_content):
        """Base identity prompt should define identity."""
        assert "IDENTITY" in base_identity_content
        assert "MIRT" in base_identity_content

    def test_base_identity_has_format_rules(self, base_identity_content):
        """Base identity prompt should define format rules."""
        assert "FORMAT RULES" in base_identity_content
        assert "messages" in base_identity_content

    def test_main_has_do_and_do_not(self, main_prompt_content):
        """Main prompt should have DO and DO NOT sections."""
        assert "## DO" in main_prompt_content
        assert "## DO NOT" in main_prompt_content

    def test_no_placeholder_text(self, base_identity_content):
        """Base identity prompt should not have placeholder text."""
        placeholders = ["TODO", "FIXME", "XXX", "PLACEHOLDER", "YOUR_NAME"]
        for ph in placeholders:
            assert ph not in base_identity_content, f"Found placeholder: {ph}"


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
