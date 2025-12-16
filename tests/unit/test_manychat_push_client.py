import asyncio

import pytest

from src.integrations.manychat.push_client import ManyChatPushClient


pytestmark = [pytest.mark.manychat]


@pytest.mark.asyncio
async def test_push_client_sanitizes_messages():
    client = ManyChatPushClient(api_url="https://api.manychat.com", api_key="key")

    messages = [
        {"type": "text", "text": "  hi  ", "extra": "ignored"},
        {"type": "text", "text": "   "},
        {"type": "image", "url": "https://example.com/a.jpg", "caption": "nope"},
        {"type": "image", "url": "  https://example.com/b.jpg  "},
    ]

    out = client._sanitize_messages(messages)

    assert out == [
        {"type": "text", "text": "hi"},
        {"type": "image", "url": "https://example.com/a.jpg"},
        {"type": "image", "url": "https://example.com/b.jpg"},
    ]


def test_push_client_build_actions_truncates_to_5():
    client = ManyChatPushClient(api_url="https://api.manychat.com", api_key="key")

    set_field_values = [
        {"field_name": f"f{i}", "field_value": str(i)} for i in range(4)
    ]
    add_tags = ["t1", "t2"]

    actions = client._build_actions(set_field_values, add_tags, remove_tags=None)

    assert len(actions) == 5
    assert actions[0]["action"] == "set_field_value"


@pytest.mark.asyncio
async def test_send_content_retries_without_actions_on_field_error(monkeypatch: pytest.MonkeyPatch):
    client = ManyChatPushClient(api_url="https://api.manychat.com", api_key="key")

    # Avoid actual sleep during typing delay
    async def _no_sleep(_: float):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    calls: list[dict] = []

    async def fake_do_send(subscriber_id, payload, headers):
        calls.append(payload)
        if len(calls) == 1:
            return False, "Field not found", 400
        return True, "ok", 200

    monkeypatch.setattr(client, "_do_send", fake_do_send)

    ok = await client.send_content(
        subscriber_id="123",
        messages=[{"type": "text", "text": "hello"}],
        set_field_values=[{"field_name": "ai_state", "field_value": "STATE_1_DISCOVERY"}],
        add_tags=["ai_responded"],
        remove_tags=["needs_human"],
        channel="instagram",
    )

    assert ok is True
    assert len(calls) == 2

    # First call includes ONLY allowed field actions in Instagram safe mode
    assert calls[0]["data"]["content"]["actions"]
    assert all(a.get("action") == "set_field_value" for a in calls[0]["data"]["content"]["actions"])
    assert {a.get("field_name") for a in calls[0]["data"]["content"]["actions"]} == {"ai_state"}

    # Retry must remove actions
    assert calls[1]["data"]["content"]["actions"] == []


@pytest.mark.asyncio
async def test_send_content_subscriber_id_casts_to_int(monkeypatch: pytest.MonkeyPatch):
    client = ManyChatPushClient(api_url="https://api.manychat.com", api_key="key")

    async def _no_sleep(_: float):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    seen: dict = {}

    async def fake_do_send(subscriber_id, payload, headers):
        seen["payload"] = payload
        return True, "ok", 200

    monkeypatch.setattr(client, "_do_send", fake_do_send)

    ok = await client.send_content(
        subscriber_id="456",
        messages=[{"type": "text", "text": "hello"}],
        channel="instagram",
    )

    assert ok is True
    assert seen["payload"]["subscriber_id"] == 456
