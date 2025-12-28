import pytest
from fastapi.testclient import TestClient


def test_sitniks_update_status_requires_token(monkeypatch: pytest.MonkeyPatch):
    from src.conf.config import settings
    from src.server.main import app

    monkeypatch.setattr(settings, "MANYCHAT_VERIFY_TOKEN", "secret", raising=False)

    client = TestClient(app)
    resp = client.post(
        "/api/v1/sitniks/update-status",
        json={"stage": "first_touch", "user_id": "u1", "instagram_username": "nick"},
        headers={"X-API-Key": "wrong"},
    )
    assert resp.status_code == 401


def test_sitniks_update_status_returns_not_configured_when_service_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    from src.conf.config import settings
    from src.server.main import app

    monkeypatch.setattr(settings, "MANYCHAT_VERIFY_TOKEN", "secret", raising=False)

    class _Svc:
        enabled = False

    # Patch factory used inside endpoint
    import src.integrations.crm.sitniks_chat_service as svc_mod

    monkeypatch.setattr(svc_mod, "get_sitniks_chat_service", lambda: _Svc())

    client = TestClient(app)
    resp = client.post(
        "/api/v1/sitniks/update-status",
        json={"stage": "first_touch", "user_id": "u1", "instagram_username": "nick"},
        headers={"X-API-Key": "secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "not configured" in body["error"].lower()


def test_sitniks_update_status_dispatches_to_correct_handler(monkeypatch: pytest.MonkeyPatch):
    from src.conf.config import settings
    from src.server.main import app

    monkeypatch.setattr(settings, "MANYCHAT_VERIFY_TOKEN", "secret", raising=False)

    calls: list[tuple[str, str]] = []

    class _Svc:
        enabled = True

        async def handle_first_touch(self, user_id: str, instagram_username=None, telegram_username=None):
            calls.append(("first_touch", user_id))
            return {"success": True}

        async def handle_give_requisites(self, user_id: str):
            calls.append(("give_requisites", user_id))
            return True

        async def handle_escalation(self, user_id: str, instagram_username=None, telegram_username=None):
            calls.append(("escalation", user_id))
            return {"success": True}

    import src.integrations.crm.sitniks_chat_service as svc_mod

    monkeypatch.setattr(svc_mod, "get_sitniks_chat_service", lambda: _Svc())

    client = TestClient(app)

    resp1 = client.post(
        "/api/v1/sitniks/update-status",
        json={"stage": "first_touch", "user_id": "u1", "instagram_username": "nick"},
        headers={"X-API-Key": "secret"},
    )
    assert resp1.status_code == 200

    resp2 = client.post(
        "/api/v1/sitniks/update-status",
        json={"stage": "give_requisites", "user_id": "u1"},
        headers={"X-API-Key": "secret"},
    )
    assert resp2.status_code == 200

    resp3 = client.post(
        "/api/v1/sitniks/update-status",
        json={"stage": "escalation", "user_id": "u1"},
        headers={"X-API-Key": "secret"},
    )
    assert resp3.status_code == 200

    assert calls == [("first_touch", "u1"), ("give_requisites", "u1"), ("escalation", "u1")]


