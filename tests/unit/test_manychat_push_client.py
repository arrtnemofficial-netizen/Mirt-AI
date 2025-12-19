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

    set_field_values = [{"field_name": f"f{i}", "field_value": str(i)} for i in range(4)]
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
        channel="facebook",
    )

    assert ok is True
    assert len(calls) == 2

    # First call includes actions
    assert calls[0]["data"]["content"]["actions"]

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


@pytest.mark.asyncio
async def test_send_content_instagram_split_send_sends_multiple_bubbles(
    monkeypatch: pytest.MonkeyPatch,
):
    client = ManyChatPushClient(api_url="https://api.manychat.com", api_key="key")

    sleeps: list[float] = []

    async def _no_sleep(seconds: float):
        sleeps.append(float(seconds))

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    calls: list[dict] = []

    async def fake_do_send(subscriber_id, payload, headers):
        calls.append(payload)
        return True, "ok", 200

    monkeypatch.setattr(client, "_do_send", fake_do_send)

    ok = await client.send_content(
        subscriber_id="123",
        channel="instagram",
        messages=[
            {"type": "text", "text": "one"},
            {"type": "text", "text": "two"},
            {"type": "text", "text": "three"},
        ],
        set_field_values=[
            {"field_name": "ai_state", "field_value": "STATE_1_DISCOVERY"},
            {"field_name": "ai_intent", "field_value": "PHOTO_IDENT"},
        ],
        add_tags=["ai_responded"],
        remove_tags=["needs_human"],
    )

    assert ok is True
    assert len(calls) == 3

    # Instagram policy: actions are disabled for reliable delivery.
    assert calls[0]["data"]["content"]["actions"] == []
    assert calls[1]["data"]["content"]["actions"] == []
    assert calls[2]["data"]["content"]["actions"] == []

    # Each sendContent call should contain exactly one message.
    assert len(calls[0]["data"]["content"]["messages"]) == 1
    assert len(calls[1]["data"]["content"]["messages"]) == 1
    assert len(calls[2]["data"]["content"]["messages"]) == 1

    # We should have at least one sleep between bubbles (default 5s) plus the initial typing delay.
    assert any(abs(s - 5.0) < 0.001 for s in sleeps)
