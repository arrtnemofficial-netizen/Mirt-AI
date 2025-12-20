"""
SMOKE: Test configuration loads correctly.

Validates that all required config values are present and valid.
"""

import pytest


@pytest.mark.smoke
@pytest.mark.critical
class TestConfigLoads:
    """Verify configuration loads and validates correctly."""

    def test_settings_object_exists(self):
        """Settings object must be created."""
        from src.conf.config import settings

        assert settings is not None

    def test_required_env_vars_structure(self):
        """Required environment variable fields exist in settings."""
        from src.conf.config import settings

        # These should exist as attributes (may be empty in test env)
        assert hasattr(settings, "TELEGRAM_BOT_TOKEN")
        assert hasattr(settings, "SUPABASE_URL")
        assert hasattr(settings, "SUPABASE_API_KEY")

    def test_payment_config_structure(self):
        """Payment config has required fields."""
        from src.conf.payment_config import BANK_REQUISITES

        assert hasattr(BANK_REQUISITES, "fop_name")
        assert hasattr(BANK_REQUISITES, "iban")
        assert hasattr(BANK_REQUISITES, "tax_id")
        assert hasattr(BANK_REQUISITES, "payment_purpose")

    def test_payment_config_values_valid(self):
        """Payment config values are sensible."""
        from src.conf.payment_config import BANK_REQUISITES

        assert len(BANK_REQUISITES.iban) > 10  # IBAN should be long
        assert len(BANK_REQUISITES.fop_name) > 0

    def test_state_enum_complete(self):
        """State enum has all required states."""
        from src.core.state_machine import State

        required_states = [
            "STATE_0_INIT",
            "STATE_1_DISCOVERY",
            "STATE_2_VISION",
            "STATE_3_SIZE_COLOR",
            "STATE_4_OFFER",
            "STATE_5_PAYMENT_DELIVERY",
            "STATE_6_UPSELL",
            "STATE_7_END",
        ]
        for state_name in required_states:
            assert hasattr(State, state_name), f"Missing state: {state_name}"

    def test_intent_enum_complete(self):
        """Intent enum has all required intents."""
        from src.core.state_machine import Intent

        required_intents = [
            "PHOTO_IDENT",
            "PAYMENT_DELIVERY",
            "COMPLAINT",
            "SIZE_HELP",
            "COLOR_HELP",
            "DISCOVERY_OR_QUESTION",
        ]
        for intent_name in required_intents:
            assert hasattr(Intent, intent_name), f"Missing intent: {intent_name}"


@pytest.mark.smoke
@pytest.mark.critical
class TestPromptFilesExist:
    """Verify all required prompt files are present."""

    def test_main_prompt_exists(self):
        """Main system prompt file exists."""
        from pathlib import Path

        prompt_path = Path("data/prompts/system/main.md")
        assert prompt_path.exists(), "Main system prompt missing"

    def test_state_prompts_exist(self):
        """State-specific prompt files exist."""
        from pathlib import Path

        required_prompts = [
            "data/prompts/states/STATE_1_DISCOVERY.md",
            "data/prompts/states/STATE_3_SIZE_COLOR.md",
            "data/prompts/states/STATE_4_OFFER.md",
            "data/prompts/states/STATE_5_PAYMENT_DELIVERY.md",
        ]
        for prompt_path in required_prompts:
            assert Path(prompt_path).exists(), f"Missing prompt: {prompt_path}"
