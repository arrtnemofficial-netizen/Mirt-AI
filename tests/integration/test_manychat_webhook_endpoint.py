from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import src.server.main as main
from src.integrations.manychat.webhook import ManychatPayloadError
from src.server.main import app
from src.services.session_store import InMemorySessionStore


pytestmark = [pytest.mark.manychat, pytest.mark.integration]


@pytest.fixture(autouse=True)
def disable_telegram_webhook(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.settings, "TELEGRAM_BOT_TOKEN", SecretStr(""))
    yield


@pytest.fixture()
def client():
    with TestClient(app) as client:
        yield client


def test_webhooks_manychat_rejects_invalid_token(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "secret")
    monkeypatch.setattr(main.settings, "MANYCHAT_PUSH_MODE", True)

    response = client.post(
        "/webhooks/manychat",
        json={
            "subscriber": {"id": "123"},
            "message": {"text": "hi"},
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid ManyChat token"


def test_webhooks_manychat_accepts_x_manychat_token_and_schedules_task(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "secret")
    monkeypatch.setattr(main.settings, "MANYCHAT_PUSH_MODE", True)
    monkeypatch.setattr(main.settings, "CELERY_ENABLED", False)

    process_message_async = AsyncMock(return_value=None)
    dummy_service = SimpleNamespace(process_message_async=process_message_async)

    with patch(
        "src.integrations.manychat.async_service.get_manychat_async_service",
        return_value=dummy_service,
    ), patch(
        "src.server.dependencies.get_session_store",
        return_value=InMemorySessionStore(),
    ), patch(
        "src.services.supabase_client.get_supabase_client",
        return_value=None,
    ):
        response = client.post(
            "/webhooks/manychat",
            headers={"X-Manychat-Token": "secret"},
            json={
                "type": "instagram",
                "subscriber": {"id": "123"},
                "message": {"text": "hi"},
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}

    process_message_async.assert_called_once_with(
        user_id="123",
        text="hi",
        image_url=None,
        channel="instagram",
        subscriber_data={"id": "123"},
    )


def test_webhooks_manychat_accepts_authorization_bearer_token(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "secret")
    monkeypatch.setattr(main.settings, "MANYCHAT_PUSH_MODE", True)
    monkeypatch.setattr(main.settings, "CELERY_ENABLED", False)

    process_message_async = AsyncMock(return_value=None)
    dummy_service = SimpleNamespace(process_message_async=process_message_async)

    with patch(
        "src.integrations.manychat.async_service.get_manychat_async_service",
        return_value=dummy_service,
    ), patch(
        "src.server.dependencies.get_session_store",
        return_value=InMemorySessionStore(),
    ), patch(
        "src.services.supabase_client.get_supabase_client",
        return_value=None,
    ):
        response = client.post(
            "/webhooks/manychat",
            headers={"Authorization": "Bearer secret"},
            json={
                "subscriber": {"id": "123"},
                "message": {"text": "hi"},
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}

    process_message_async.assert_called_once_with(
        user_id="123",
        text="hi",
        image_url=None,
        channel="instagram",
        subscriber_data={"id": "123"},
    )


def test_webhooks_manychat_accepts_image_only_in_push_mode(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "")
    monkeypatch.setattr(main.settings, "MANYCHAT_PUSH_MODE", True)
    monkeypatch.setattr(main.settings, "CELERY_ENABLED", False)

    process_message_async = AsyncMock(return_value=None)
    dummy_service = SimpleNamespace(process_message_async=process_message_async)

    with patch(
        "src.integrations.manychat.async_service.get_manychat_async_service",
        return_value=dummy_service,
    ), patch(
        "src.server.dependencies.get_session_store",
        return_value=InMemorySessionStore(),
    ), patch(
        "src.services.supabase_client.get_supabase_client",
        return_value=None,
    ):
        response = client.post(
            "/webhooks/manychat",
            json={
                "subscriber": {"id": "123"},
                "message": {
                    "attachments": [
                        {
                            "type": "image",
                            "payload": {"url": "https://example.com/photo.jpg"},
                        }
                    ]
                },
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}

    process_message_async.assert_called_once_with(
        user_id="123",
        text="",
        image_url="https://example.com/photo.jpg",
        channel="instagram",
        subscriber_data={"id": "123"},
    )


def test_webhooks_manychat_missing_message_and_image_returns_400_in_push_mode(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "")
    monkeypatch.setattr(main.settings, "MANYCHAT_PUSH_MODE", True)

    response = client.post(
        "/webhooks/manychat",
        json={
            "subscriber": {"id": "123"},
            "message": {},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing message text or image"


def test_webhooks_manychat_response_mode_returns_handler_output(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "")
    monkeypatch.setattr(main.settings, "MANYCHAT_PUSH_MODE", False)

    expected = {
        "version": "v2",
        "content": {
            "messages": [{"type": "text", "text": "ok"}],
            "actions": [],
            "quick_replies": [],
        },
    }

    dummy_handler = SimpleNamespace(handle=AsyncMock(return_value=expected))

    payload = {"subscriber": {"id": "123"}, "message": {"text": "hi"}}

    with patch("src.server.main.get_cached_manychat_handler", return_value=dummy_handler):
        response = client.post("/webhooks/manychat", json=payload)

    assert response.status_code == 200
    assert response.json() == expected

    dummy_handler.handle.assert_awaited_once_with(payload)


def test_webhooks_manychat_response_mode_payload_error_returns_400(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "")
    monkeypatch.setattr(main.settings, "MANYCHAT_PUSH_MODE", False)

    dummy_handler = SimpleNamespace(handle=AsyncMock(side_effect=ManychatPayloadError("bad")))

    with patch("src.server.main.get_cached_manychat_handler", return_value=dummy_handler):
        response = client.post(
            "/webhooks/manychat",
            json={"subscriber": {"id": "123"}, "message": {}},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "bad"


def test_webhooks_manychat_push_mode_dedupes_by_message_id(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "")
    monkeypatch.setattr(main.settings, "MANYCHAT_PUSH_MODE", True)
    monkeypatch.setattr(main.settings, "CELERY_ENABLED", False)

    process_message_async = AsyncMock(return_value=None)
    dummy_service = SimpleNamespace(process_message_async=process_message_async)

    payload = {
        "subscriber": {"id": "123"},
        "message": {"id": "m1", "text": "hi"},
    }

    with patch(
        "src.integrations.manychat.async_service.get_manychat_async_service",
        return_value=dummy_service,
    ), patch(
        "src.server.dependencies.get_session_store",
        return_value=InMemorySessionStore(),
    ), patch(
        "src.services.supabase_client.get_supabase_client",
        return_value=object(),
    ), patch(
        "src.services.webhook_dedupe.WebhookDedupeStore.check_and_mark",
        side_effect=[False, True],
    ):
        r1 = client.post("/webhooks/manychat", json=payload)
        r2 = client.post("/webhooks/manychat", json=payload)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == {"status": "accepted"}
    assert r2.json() == {"status": "accepted"}

    process_message_async.assert_called_once()
