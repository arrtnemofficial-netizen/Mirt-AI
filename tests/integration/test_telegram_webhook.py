from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.server import main
from src.server.main import app


pytestmark = [pytest.mark.telegram, pytest.mark.integration]


@pytest.fixture(autouse=True)
def disable_telegram_webhook_registration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.settings, "TELEGRAM_BOT_TOKEN", SecretStr(""))
    yield


@pytest.fixture()
def client():
    with TestClient(app) as client:
        yield client


def test_telegram_webhook_calls_dispatcher(client, monkeypatch: pytest.MonkeyPatch):
    dummy_bot = object()
    feed_update = AsyncMock(return_value=None)

    class DummyDispatcher:
        async def feed_update(self, bot, update):
            return await feed_update(bot=bot, update=update)

    dummy_dp = DummyDispatcher()

    monkeypatch.setattr(main, "get_bot", lambda: dummy_bot)
    monkeypatch.setattr(main, "get_cached_dispatcher", lambda: dummy_dp)

    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1710000000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 456, "is_bot": False, "first_name": "Test"},
            "text": "hi",
        },
    }

    response = client.post(main.settings.TELEGRAM_WEBHOOK_PATH, json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    assert feed_update.await_count == 1
    kwargs = feed_update.await_args.kwargs
    assert kwargs["bot"] is dummy_bot

    update = kwargs["update"]
    assert update.update_id == 1
    assert update.message.text == "hi"
