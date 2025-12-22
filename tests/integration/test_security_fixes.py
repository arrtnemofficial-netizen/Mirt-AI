"""Integration tests for security fixes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.server.main import app

client = TestClient(app)


class TestManyChatWebhookSecurity:
    """Integration tests for ManyChat webhook security."""

    def test_webhook_with_invalid_token_returns_401(self, monkeypatch):
        """Test that webhook rejects requests with invalid token."""
        monkeypatch.setenv("MANYCHAT_VERIFY_TOKEN", "test_token_123")
        response = client.post(
            "/webhooks/manychat",
            json={"subscriber": {"id": "123"}, "message": {"text": "Hello"}},
            headers={"X-ManyChat-Token": "wrong_token"},
        )
        assert response.status_code == 401
        assert "Invalid token" in response.json()["detail"]

    def test_webhook_without_token_when_not_configured_returns_503(self, monkeypatch):
        """Test that webhook returns 503 when token is not configured."""
        monkeypatch.delenv("MANYCHAT_VERIFY_TOKEN", raising=False)
        response = client.post(
            "/webhooks/manychat",
            json={"subscriber": {"id": "123"}, "message": {"text": "Hello"}},
        )
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()

    def test_webhook_blocks_ssrf_image_url(self, monkeypatch):
        """Test that webhook blocks SSRF attempts via image_url."""
        monkeypatch.setenv("MANYCHAT_VERIFY_TOKEN", "test_token_123")
        response = client.post(
            "/webhooks/manychat",
            json={
                "subscriber": {"id": "123"},
                "data": {"image_url": "http://localhost/test.jpg"},
            },
            headers={"X-ManyChat-Token": "test_token_123"},
        )
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "localhost" in detail or "not allowed" in detail