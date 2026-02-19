"""Behavior-based security tests for auth and rate limiting."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from src.conf.config import settings


@pytest.mark.security
class TestAuthBehavior:
    """Verify protected endpoints enforce token checks."""

    def test_manychat_webhook_invalid_token_returns_401(self, monkeypatch):
        monkeypatch.setattr(settings, "MANYCHAT_VERIFY_TOKEN", "secret-token")

        from src.server.main import app

        client = TestClient(app)
        response = client.post(
            "/webhooks/manychat",
            json={"subscriber": {"id": "123"}, "message": {"text": "привіт"}},
            headers={"X-ManyChat-Token": "wrong-token"},
        )
        assert response.status_code == 401

    def test_api_v1_invalid_token_returns_401(self, monkeypatch):
        monkeypatch.setattr(settings, "MANYCHAT_VERIFY_TOKEN", "secret-token")

        from src.server.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/messages",
            json={"clientId": "123", "message": "привіт"},
            headers={"X-API-Key": "wrong-token"},
        )
        assert response.status_code == 401

    def test_api_v1_valid_token_is_accepted(self, monkeypatch):
        monkeypatch.setattr(settings, "MANYCHAT_VERIFY_TOKEN", "secret-token")

        from src.server.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/messages",
            json={"clientId": "123", "message": "привіт"},
            headers={"X-API-Key": "secret-token"},
        )
        assert response.status_code == 202


@pytest.mark.security
class TestRateLimitBehavior:
    """Verify rate limiting returns HTTP 429 when exceeded."""

    def test_middleware_rate_limit_returns_429(self):
        from src.server.middleware import RateLimitConfig, RateLimitMiddleware

        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            config=RateLimitConfig(
                requests_per_minute=1,
                requests_per_hour=10,
                excluded_paths=[],
            ),
        )

        @app.post("/limited")
        async def limited(request: Request) -> dict[str, bool]:
            return {"ok": True}

        client = TestClient(app)
        first = client.post("/limited")
        second = client.post("/limited")

        assert first.status_code == 200
        assert second.status_code == 429
