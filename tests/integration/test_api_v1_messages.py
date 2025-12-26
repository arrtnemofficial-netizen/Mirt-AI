from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.server import main
from src.server.main import app
from src.services.storage import InMemorySessionStore


pytestmark = [pytest.mark.manychat, pytest.mark.integration]


@pytest.fixture(autouse=True)
def disable_telegram_webhook(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.settings, "TELEGRAM_BOT_TOKEN", SecretStr(""))
    yield


@pytest.fixture()
def client():
    with TestClient(app) as client:
        yield client


def test_api_v1_messages_rejects_invalid_token(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "secret")

    response = client.post(
        "/api/v1/messages",
        json={
            "clientId": "123",
            "message": "hi",
        },
    )

    assert response.status_code == 401


def test_api_v1_messages_accepts_x_api_key_and_schedules_task(
    client, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "secret")

    process_message_async = AsyncMock(return_value=None)
    dummy_service = SimpleNamespace(process_message_async=process_message_async)

    with (
        patch(
            "src.integrations.manychat.async_service.get_manychat_async_service",
            return_value=dummy_service,
        ),
        patch(
            "src.server.dependencies.get_session_store",
            return_value=InMemorySessionStore(),
        ),
    ):
        response = client.post(
            "/api/v1/messages",
            headers={"X-API-Key": "secret"},
            json={
                "type": "instagram",
                "clientId": "123",
                "message": "hi",
            },
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}

    process_message_async.assert_called_once_with(
        user_id="123",
        text="hi",
        image_url=None,
        channel="instagram",
        trace_id=ANY,
    )


def test_api_v1_messages_accepts_bearer_token(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "secret")

    process_message_async = AsyncMock(return_value=None)
    dummy_service = SimpleNamespace(process_message_async=process_message_async)

    with (
        patch(
            "src.integrations.manychat.async_service.get_manychat_async_service",
            return_value=dummy_service,
        ),
        patch(
            "src.server.dependencies.get_session_store",
            return_value=InMemorySessionStore(),
        ),
    ):
        response = client.post(
            "/api/v1/messages",
            headers={"Authorization": "Bearer secret"},
            json={
                "clientId": "123",
                "message": "hi",
            },
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}

    process_message_async.assert_called_once_with(
        user_id="123",
        text="hi",
        image_url=None,
        channel="instagram",
        trace_id=ANY,
    )


def test_api_v1_messages_accepts_messages_alias(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "secret")

    process_message_async = AsyncMock(return_value=None)
    dummy_service = SimpleNamespace(process_message_async=process_message_async)

    with (
        patch(
            "src.integrations.manychat.async_service.get_manychat_async_service",
            return_value=dummy_service,
        ),
        patch(
            "src.server.dependencies.get_session_store",
            return_value=InMemorySessionStore(),
        ),
    ):
        response = client.post(
            "/api/v1/messages",
            headers={"X-API-Key": "secret"},
            json={
                "clientId": "123",
                "messages": "hi",
            },
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}

    process_message_async.assert_called_once_with(
        user_id="123",
        text="hi",
        image_url=None,
        channel="instagram",
        trace_id=ANY,
    )


def test_api_v1_messages_accepts_image_only(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "secret")

    process_message_async = AsyncMock(return_value=None)
    dummy_service = SimpleNamespace(process_message_async=process_message_async)

    with (
        patch(
            "src.integrations.manychat.async_service.get_manychat_async_service",
            return_value=dummy_service,
        ),
        patch(
            "src.server.dependencies.get_session_store",
            return_value=InMemorySessionStore(),
        ),
    ):
        response = client.post(
            "/api/v1/messages",
            headers={"X-API-Key": "secret"},
            json={
                "clientId": "123",
                "imageUrl": "https://example.com/photo.jpg",
            },
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}

    process_message_async.assert_called_once_with(
        user_id="123",
        text="",
        image_url="https://example.com/photo.jpg",
        channel="instagram",
        trace_id=ANY,
    )


def test_api_v1_messages_strips_manychat_prefix_dot_semicolon(
    client, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "secret")

    process_message_async = AsyncMock(return_value=None)
    dummy_service = SimpleNamespace(process_message_async=process_message_async)

    with (
        patch(
            "src.integrations.manychat.async_service.get_manychat_async_service",
            return_value=dummy_service,
        ),
        patch(
            "src.server.dependencies.get_session_store",
            return_value=InMemorySessionStore(),
        ),
    ):
        response = client.post(
            "/api/v1/messages",
            headers={"X-API-Key": "secret"},
            json={
                "clientId": "123",
                "message": ".; /restart",
            },
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}

    process_message_async.assert_called_once_with(
        user_id="123",
        text="/restart",
        image_url=None,
        channel="instagram",
        trace_id=ANY,
    )


def test_api_v1_messages_removes_embedded_image_url_from_text(
    client, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "secret")

    process_message_async = AsyncMock(return_value=None)
    dummy_service = SimpleNamespace(process_message_async=process_message_async)

    with (
        patch(
            "src.integrations.manychat.async_service.get_manychat_async_service",
            return_value=dummy_service,
        ),
        patch(
            "src.server.dependencies.get_session_store",
            return_value=InMemorySessionStore(),
        ),
    ):
        response = client.post(
            "/api/v1/messages",
            headers={"X-API-Key": "secret"},
            json={
                "clientId": "123",
                "message": ".; https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1&signature=abc; Хочу",
            },
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}

    process_message_async.assert_called_once()
    kwargs = process_message_async.call_args.kwargs
    assert kwargs["user_id"] == "123"
    assert kwargs["channel"] == "instagram"
    assert kwargs["image_url"] is not None
    assert "lookaside.fbsbx.com" in kwargs["image_url"]
    assert "lookaside.fbsbx.com" not in kwargs["text"].lower()


def test_api_v1_messages_missing_message_and_image_returns_400(
    client, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(main.settings, "MANYCHAT_VERIFY_TOKEN", "")

    response = client.post(
        "/api/v1/messages",
        json={
            "clientId": "123",
        },
    )

    assert response.status_code == 400
