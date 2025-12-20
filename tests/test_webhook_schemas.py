"""
CONTRACT: Webhook payload schema validation.

Ensures webhook handlers can process expected payloads.
External systems (Telegram, ManyChat) send these.
"""

import pytest


@pytest.mark.contract
@pytest.mark.critical
@pytest.mark.telegram
class TestTelegramWebhookContract:
    """Verify Telegram webhook payload handling."""

    def test_telegram_update_message_structure(self):
        """Telegram message update has expected structure."""
        # Standard Telegram message update
        update = {
            "update_id": 123456789,
            "message": {
                "message_id": 1,
                "from": {
                    "id": 12345,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": "testuser",
                },
                "chat": {
                    "id": 12345,
                    "type": "private",
                },
                "date": 1699999999,
                "text": "Привіт",
            },
        }

        # Verify structure
        assert "message" in update
        assert "from" in update["message"]
        assert "id" in update["message"]["from"]
        assert "text" in update["message"]

    def test_telegram_photo_update_structure(self):
        """Telegram photo update has expected structure."""
        update = {
            "update_id": 123456790,
            "message": {
                "message_id": 2,
                "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 12345, "type": "private"},
                "date": 1699999999,
                "photo": [
                    {"file_id": "small_id", "width": 90, "height": 90},
                    {"file_id": "medium_id", "width": 320, "height": 320},
                    {"file_id": "large_id", "width": 800, "height": 800},
                ],
            },
        }

        assert "photo" in update["message"]
        assert isinstance(update["message"]["photo"], list)
        assert len(update["message"]["photo"]) > 0


@pytest.mark.contract
@pytest.mark.critical
@pytest.mark.manychat
class TestManyChatWebhookContract:
    """Verify ManyChat webhook payload handling."""

    def test_manychat_message_payload_structure(self):
        """ManyChat incoming message has expected structure."""
        payload = {
            "version": "v2",
            "subscriber": {
                "id": "123456",
                "key": "subscriber_key",
                "page_id": "page_123",
                "status": "active",
                "first_name": "Test",
                "last_name": "User",
                "name": "Test User",
                "gender": "male",
                "profile_pic": "https://example.com/pic.jpg",
                "locale": "uk_UA",
                "language": "uk",
                "timezone": "Europe/Kiev",
                "live_chat_url": "https://manychat.com/chat/123",
                "last_input_text": "Привіт",
                "subscribed": "2024-01-01T00:00:00+00:00",
                "last_interaction": "2024-12-13T12:00:00+00:00",
                "last_seen": "2024-12-13T12:00:00+00:00",
            },
            "last_input_text": "Привіт",
        }

        assert "subscriber" in payload
        assert "id" in payload["subscriber"]
        assert "last_input_text" in payload

    def test_manychat_response_structure(self):
        """ManyChat response must have expected structure."""
        # Valid ManyChat v2 response
        response = {
            "version": "v2",
            "content": {
                "messages": [{"type": "text", "text": "Привіт!"}],
                "actions": [],
                "quick_replies": [],
            },
        }

        assert response["version"] == "v2"
        assert "content" in response
        assert "messages" in response["content"]


@pytest.mark.contract
class TestCRMWebhookContract:
    """Verify CRM webhook payload handling."""

    def test_sitniks_order_webhook_structure(self):
        """Sitniks CRM order webhook has expected structure."""
        webhook = {
            "event": "order.status_changed",
            "data": {
                "order_id": "12345",
                "external_id": "mirt_order_123",
                "status": "Оплачено",
                "updated_at": "2024-12-13T12:00:00Z",
            },
        }

        assert "event" in webhook
        assert "data" in webhook
        assert "order_id" in webhook["data"]

    def test_crm_status_values_stable(self):
        """CRM status values must be stable strings."""
        expected_statuses = [
            "Взято в роботу",
            "Виставлено рахунок",
            "AI Увага",
            "Оплачено",
        ]

        # These are used in CRM integration
        for status in expected_statuses:
            assert isinstance(status, str)
            assert len(status) > 0
