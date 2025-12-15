"""Tests for ManyChat follow-up endpoint."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.server.main import _generate_followup_text, app


# Mock settings to disable token verification in tests
pytestmark = [pytest.mark.manychat, pytest.mark.integration]

@pytest.fixture(autouse=True)
def mock_settings():
    with patch("src.server.main.settings") as mock:
        mock.MANYCHAT_VERIFY_TOKEN = ""  # Disable token check
        yield mock


client = TestClient(app)


class TestFollowupEndpoint:
    """Test /webhooks/manychat/followup endpoint."""

    def test_followup_discovery_state(self):
        """Follow-up needed for DISCOVERY state."""
        response = client.post(
            "/webhooks/manychat/followup",
            json={
                "subscriber": {"id": "123"},
                "custom_fields": {"ai_state": "STATE_1_DISCOVERY"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["needs_followup"] is True
        assert data["followup_text"] != ""
        assert data["current_state"] == "STATE_1_DISCOVERY"

    def test_followup_offer_state_with_product(self):
        """Follow-up for OFFER state includes product name."""
        response = client.post(
            "/webhooks/manychat/followup",
            json={
                "subscriber": {"id": "123"},
                "custom_fields": {
                    "ai_state": "STATE_4_OFFER",
                    "last_product": "Сукня Анна",
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["needs_followup"] is True
        assert "Сукня Анна" in data["followup_text"]

    def test_no_followup_for_completed_order(self):
        """No follow-up for STATE_7_END (order completed)."""
        response = client.post(
            "/webhooks/manychat/followup",
            json={
                "subscriber": {"id": "123"},
                "custom_fields": {"ai_state": "STATE_7_END"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["needs_followup"] is False
        assert data["followup_text"] == ""

    def test_no_followup_for_init_state(self):
        """No follow-up for STATE_0_INIT (not started)."""
        response = client.post(
            "/webhooks/manychat/followup",
            json={
                "subscriber": {"id": "123"},
                "custom_fields": {"ai_state": "STATE_0_INIT"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["needs_followup"] is False

    def test_followup_payment_state(self):
        """Follow-up for payment state asks for delivery data."""
        response = client.post(
            "/webhooks/manychat/followup",
            json={
                "subscriber": {"id": "123"},
                "custom_fields": {"ai_state": "STATE_5_PAYMENT_DELIVERY"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["needs_followup"] is True
        assert "ПІБ" in data["followup_text"] or "Нова" in data["followup_text"]

    def test_followup_unknown_user(self):
        """No follow-up for unknown user."""
        response = client.post(
            "/webhooks/manychat/followup",
            json={
                "subscriber": {},
                "custom_fields": {"ai_state": "STATE_4_OFFER"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["needs_followup"] is False
        assert data.get("reason") == "unknown_user"

    def test_followup_includes_set_field_values(self):
        """Response includes set_field_values for ManyChat."""
        response = client.post(
            "/webhooks/manychat/followup",
            json={
                "subscriber": {"id": "123"},
                "custom_fields": {"ai_state": "STATE_4_OFFER"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "set_field_values" in data
        assert len(data["set_field_values"]) > 0

    def test_followup_includes_add_tag(self):
        """Response includes add_tag when followup needed."""
        response = client.post(
            "/webhooks/manychat/followup",
            json={
                "subscriber": {"id": "123"},
                "custom_fields": {"ai_state": "STATE_4_OFFER"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "add_tag" in data
        assert "followup_sent" in data["add_tag"]


class TestGenerateFollowupText:
    """Test _generate_followup_text helper."""

    def test_discovery_state(self):
        text = _generate_followup_text("STATE_1_DISCOVERY")
        assert text is not None
        assert "одяг" in text.lower() or "підказати" in text.lower()

    def test_vision_state(self):
        text = _generate_followup_text("STATE_2_VISION")
        assert text is not None
        assert "кольор" in text.lower() or "розмір" in text.lower()

    def test_offer_with_product(self):
        text = _generate_followup_text("STATE_4_OFFER", "Костюм Макс")
        assert text is not None
        assert "Костюм Макс" in text

    def test_end_state_no_followup(self):
        text = _generate_followup_text("STATE_7_END")
        assert text is None

    def test_complaint_state_no_followup(self):
        text = _generate_followup_text("STATE_8_COMPLAINT")
        assert text is None

    def test_unknown_state_default(self):
        text = _generate_followup_text("UNKNOWN_STATE")
        assert text is not None
        assert "допомогти" in text.lower()
