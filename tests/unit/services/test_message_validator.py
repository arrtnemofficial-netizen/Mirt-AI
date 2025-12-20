"""
Tests for input validator (InputMetadata, WebhookInput).
=========================================================
Updated for new architecture with input_validator.py
"""

from src.core.input_validator import (
    InputMetadata,
    WebhookInput,
    validate_input_metadata,
    validate_webhook_input,
)
from src.core.state_machine import EscalationLevel, Intent, State


# =============================================================================
# INPUT METADATA TESTS
# =============================================================================


class TestInputMetadata:
    """Test InputMetadata validation."""

    def test_valid_metadata(self):
        """Test valid metadata passes."""
        meta = InputMetadata(
            session_id="test-123",
            current_state=State.STATE_0_INIT,
            channel="telegram",
        )

        assert meta.session_id == "test-123"
        assert meta.current_state == State.STATE_0_INIT
        assert meta.channel == "telegram"

    def test_empty_session_id_allowed(self):
        """Test empty session_id is allowed (uses default)."""
        meta = InputMetadata()

        assert meta.session_id == ""
        assert meta.current_state == State.STATE_0_INIT

    def test_state_normalization_from_string(self):
        """Test state is normalized from string."""
        meta = InputMetadata(current_state="STATE1_DISCOVERY")  # Legacy format

        assert meta.current_state == State.STATE_1_DISCOVERY

    def test_state_normalization_lowercase(self):
        """Test state handles lowercase."""
        meta = InputMetadata(current_state="state_0_init")

        assert meta.current_state == State.STATE_0_INIT

    def test_invalid_state_defaults_to_init(self):
        """Test invalid state defaults to STATE_0_INIT."""
        meta = InputMetadata(current_state="INVALID_STATE")

        assert meta.current_state == State.STATE_0_INIT

    def test_intent_normalization(self):
        """Test intent is normalized."""
        meta = InputMetadata(intent="greeting_only")

        assert meta.intent == Intent.GREETING_ONLY

    def test_intent_none_allowed(self):
        """Test None intent is allowed."""
        meta = InputMetadata(intent=None)

        assert meta.intent is None

    def test_channel_normalization(self):
        """Test channel is normalized to lowercase."""
        meta = InputMetadata(channel="TELEGRAM")

        assert meta.channel == "telegram"

    def test_channel_empty_defaults_unknown(self):
        """Test empty channel defaults to 'unknown'."""
        meta = InputMetadata(channel="")

        assert meta.channel == "unknown"

    def test_image_url_sets_has_image(self):
        """Test image_url sets has_image automatically."""
        meta = InputMetadata(image_url="https://example.com/image.jpg", has_image=True)

        assert meta.has_image is True

    def test_has_image_explicit(self):
        """Test has_image can be set explicitly."""
        meta = InputMetadata(has_image=True)

        assert meta.has_image is True

    def test_escalation_level_normalization(self):
        """Test escalation level is normalized."""
        meta = InputMetadata(escalation_level="l1")

        assert meta.escalation_level == EscalationLevel.L1

    def test_to_agent_metadata(self):
        """Test conversion to agent metadata dict."""
        meta = InputMetadata(
            session_id="test",
            current_state=State.STATE_1_DISCOVERY,
            intent=Intent.GREETING_ONLY,
            channel="telegram",
        )

        result = meta.to_agent_metadata()

        assert result["session_id"] == "test"
        assert result["current_state"] == "STATE_1_DISCOVERY"
        assert result["intent"] == "GREETING_ONLY"
        assert result["channel"] == "telegram"


# =============================================================================
# WEBHOOK INPUT TESTS
# =============================================================================


class TestWebhookInput:
    """Test WebhookInput validation."""

    def test_valid_webhook_input(self):
        """Test valid webhook input."""
        data = WebhookInput(
            text="Привіт, шукаю сукню",
            session_id="session-123",
        )

        assert data.text == "Привіт, шукаю сукню"
        assert data.session_id == "session-123"

    def test_empty_text_allowed(self):
        """Test empty text is allowed."""
        data = WebhookInput(text="")

        assert data.text == ""

    def test_none_text_becomes_empty(self):
        """Test None text becomes empty string."""
        data = WebhookInput(text=None)

        assert data.text == ""

    def test_text_whitespace_trimmed(self):
        """Test text whitespace is trimmed."""
        data = WebhookInput(text="  Привіт  ")

        assert data.text == "Привіт"

    def test_with_image_url(self):
        """Test webhook with image URL."""
        data = WebhookInput(
            text="Що це?",
            image_url="https://example.com/photo.jpg",
        )

        assert data.image_url == "https://example.com/photo.jpg"


# =============================================================================
# CONVENIENCE FUNCTIONS TESTS
# =============================================================================


class TestConvenienceFunctions:
    """Test convenience validation functions."""

    def test_validate_input_metadata_valid(self):
        """Test validating valid metadata dict."""
        raw = {
            "session_id": "test",
            "current_state": "STATE_1_DISCOVERY",
            "channel": "instagram",
        }

        result = validate_input_metadata(raw)

        assert result.session_id == "test"
        assert result.current_state == State.STATE_1_DISCOVERY
        assert result.channel == "instagram"

    def test_validate_input_metadata_invalid(self):
        """Test validating invalid metadata returns defaults."""
        raw = "invalid"  # Not a dict

        result = validate_input_metadata(raw)

        assert result.session_id == ""
        assert result.current_state == State.STATE_0_INIT

    def test_validate_webhook_input_valid(self):
        """Test validating valid webhook input."""
        raw = {
            "text": "Привіт",
            "session_id": "session-456",
        }

        result = validate_webhook_input(raw)

        assert result.text == "Привіт"
        assert result.session_id == "session-456"

    def test_validate_webhook_input_partial(self):
        """Test validating partial webhook input."""
        raw = {"text": "Hello"}

        result = validate_webhook_input(raw)

        assert result.text == "Hello"
        assert result.session_id == ""


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Test edge cases."""

    def test_unicode_text(self):
        """Test Ukrainian text is handled."""
        data = WebhookInput(text="Привіт! Шукаю сукню для дитини 🎀")

        assert "Привіт" in data.text
        assert "🎀" in data.text

    def test_very_long_session_id(self):
        """Test very long session ID."""
        long_id = "a" * 1000
        meta = InputMetadata(session_id=long_id)

        assert meta.session_id == long_id

    def test_moderation_flags_list(self):
        """Test moderation flags list."""
        meta = InputMetadata(moderation_flags=["email", "phone"])

        assert len(meta.moderation_flags) == 2
        assert "email" in meta.moderation_flags

    def test_empty_moderation_flags(self):
        """Test empty moderation flags."""
        meta = InputMetadata()

        assert meta.moderation_flags == []
