import pytest

from src.core.models import AgentResponse, Message, Metadata, Product
from src.integrations.manychat.async_service import ManyChatAsyncService
from src.integrations.manychat.response_builder import build_manychat_messages
from src.integrations.manychat.webhook import ManychatWebhook
from src.services.session_store import InMemorySessionStore


pytestmark = [pytest.mark.manychat]


class DummyPushClient:
    def __init__(self):
        self.calls = []

    async def send_content(
        self,
        subscriber_id: str,
        messages,
        *,
        channel: str = "instagram",
        quick_replies=None,
        set_field_values=None,
        add_tags=None,
        remove_tags=None,
        message_tag: str = "ACCOUNT_UPDATE",
    ) -> bool:
        self.calls.append(
            {
                "subscriber_id": subscriber_id,
                "messages": messages,
                "channel": channel,
                "quick_replies": quick_replies,
                "set_field_values": set_field_values,
                "add_tags": add_tags,
                "remove_tags": remove_tags,
                "message_tag": message_tag,
            }
        )
        return True

    async def send_text(self, subscriber_id: str, text: str, *, channel: str = "instagram") -> bool:
        self.calls.append(
            {
                "subscriber_id": subscriber_id,
                "messages": [{"type": "text", "text": text}],
                "channel": channel,
                "send_text": True,
            }
        )
        return True


class DummyDebouncer:
    def __init__(self, aggregated):
        self.aggregated = aggregated
        self.calls = []

    async def wait_for_debounce(self, user_id: str, buffered_msg):
        self.calls.append({"user_id": user_id, "buffered_msg": buffered_msg})
        return self.aggregated


class DummyHandler:
    def __init__(self, response: AgentResponse):
        self.response = response
        self.calls = []

    async def process_message(self, session_id: str, text: str, *, extra_metadata=None):
        self.calls.append(
            {"session_id": session_id, "text": text, "extra_metadata": extra_metadata}
        )
        return type(
            "Res",
            (),
            {"response": self.response, "state": {}, "error": None, "is_fallback": False},
        )()

class DummyMessageStore:
    def __init__(self):
        self.delete_calls = []

    def append(self, message):
        pass

    def list(self, session_id: str):
        return []

    def delete(self, session_id: str) -> None:
        self.delete_calls.append(session_id)



@pytest.mark.asyncio
async def test_push_response_builds_text_and_image_messages(monkeypatch: pytest.MonkeyPatch):
    store = InMemorySessionStore()
    push_client = DummyPushClient()
    message_store = DummyMessageStore()

    svc = ManyChatAsyncService(
        store,
        runner=object(),
        push_client=push_client,
        message_store=message_store,
    )

    agent_response = AgentResponse(
        event="simple_answer",
        messages=[Message(content="Hello")],
        products=[
            Product.from_legacy(
                {
                    "product_id": 1,
                    "name": "Сукня",
                    "price": 100,
                    "photo_url": "https://example.com/p.jpg",
                }
            )
        ],
        metadata=Metadata(current_state="STATE_4_OFFER", intent="DISCOVERY_OR_QUESTION"),
    )

    await svc._push_response("u1", agent_response, "instagram")

    assert len(push_client.calls) == 1
    call = push_client.calls[0]

    assert call["subscriber_id"] == "u1"
    assert call["channel"] == "instagram"

    # First chunk is text, then image appended
    assert call["messages"][0]["type"] == "text"
    assert "Hello" in call["messages"][0]["text"]
    assert any(m.get("type") == "image" for m in call["messages"])


def test_build_manychat_messages_preserves_inline_image_order():
    agent_response = AgentResponse(
        event="simple_answer",
        messages=[
            Message(content="Це наш Костюм Лагуна!"),
            Message(type="image", content="https://example.com/laguna.jpg"),
            Message(content="На який зріст підказати?"),
        ],
        products=[
            # Same URL as the inline image: should not duplicate.
            Product.from_legacy(
                {
                    "product_id": 1,
                    "name": "Костюм Лагуна",
                    "price": 100,
                    "photo_url": "https://example.com/laguna.jpg",
                }
            )
        ],
        metadata=Metadata(current_state="STATE_2_VISION", intent="PHOTO_IDENT"),
    )

    messages = build_manychat_messages(agent_response, include_product_images=True)

    assert messages[0] == {"type": "text", "text": "Це наш Костюм Лагуна!"}
    assert messages[1] == {"type": "image", "url": "https://example.com/laguna.jpg"}
    assert messages[2] == {"type": "text", "text": "На який зріст підказати?"}
    assert [m for m in messages if m.get("type") == "image"] == [
        {"type": "image", "url": "https://example.com/laguna.jpg"}
    ]


@pytest.mark.asyncio
async def test_process_message_async_restart_clears_session_and_sends_text(
    monkeypatch: pytest.MonkeyPatch,
):
    store = InMemorySessionStore()
    push_client = DummyPushClient()
    message_store = DummyMessageStore()

    svc = ManyChatAsyncService(
        store,
        runner=object(),
        push_client=push_client,
        message_store=message_store,
    )

    # Seed a session to ensure delete() returns True
    store.save("u2", {"messages": [], "metadata": {}, "current_state": "STATE_0_INIT"})

    await svc.process_message_async(
        user_id="u2", text="/restart", image_url=None, channel="instagram"
    )

    assert len(push_client.calls) == 1
    assert push_client.calls[0].get("send_text") is True
    assert message_store.delete_calls == ["u2"]
    assert "Сесія очищена" in push_client.calls[0]["messages"][0]["text"]


def test_restart_command_only_exact_token():
    def _first_token(text: str) -> str:
        return ManyChatAsyncService._normalize_command_text(text)[2]

    true_cases = ["/restart", "/Restart", ".; /restart", "  /restart now"]
    for text in true_cases:
        assert ManyChatAsyncService._is_restart_command(_first_token(text)) is True

    false_cases = ["/start", "restart", "/restart123", "/restart/now", "/restar"]
    for text in false_cases:
        assert ManyChatAsyncService._is_restart_command(_first_token(text)) is False


@pytest.mark.asyncio
async def test_process_message_async_uses_debouncer_and_handler(monkeypatch: pytest.MonkeyPatch):
    store = InMemorySessionStore()
    push_client = DummyPushClient()
    message_store = DummyMessageStore()

    svc = ManyChatAsyncService(
        store,
        runner=object(),
        push_client=push_client,
        message_store=message_store,
    )

    aggregated = type(
        "Agg",
        (),
        {
            "text": "hi",
            "extra_metadata": {"has_image": True, "image_url": "https://example.com/u.jpg"},
        },
    )()

    svc.debouncer = DummyDebouncer(aggregated)

    agent_response = AgentResponse(
        event="simple_answer",
        messages=[Message(content="ok")],
        products=[],
        metadata=Metadata(current_state="STATE_1_DISCOVERY", intent="GREETING_ONLY"),
    )
    svc._handler = DummyHandler(agent_response)

    await svc.process_message_async(
        user_id="u3",
        text="hi",
        image_url="https://example.com/u.jpg",
        channel="instagram",
    )

    assert len(svc.debouncer.calls) == 1
    assert len(svc._handler.calls) == 1
    assert svc._handler.calls[0]["extra_metadata"]["image_url"] == "https://example.com/u.jpg"

    assert len(push_client.calls) == 1
    assert push_client.calls[0]["subscriber_id"] == "u3"


@pytest.mark.asyncio
async def test_process_message_async_superseded_request_is_silent(monkeypatch: pytest.MonkeyPatch):
    store = InMemorySessionStore()
    push_client = DummyPushClient()
    message_store = DummyMessageStore()

    svc = ManyChatAsyncService(
        store,
        runner=object(),
        push_client=push_client,
        message_store=message_store,
    )

    svc.debouncer = DummyDebouncer(aggregated=None)

    await svc.process_message_async(user_id="u4", text="hi", image_url=None, channel="instagram")

    assert push_client.calls == []


@pytest.mark.asyncio
async def test_sync_and_async_manychat_builders_do_not_drift_on_fields_tags_and_text():
    store = InMemorySessionStore()

    agent_response = AgentResponse(
        event="simple_answer",
        messages=[Message(content="Hello")],
        products=[
            Product.from_legacy(
                {
                    "product_id": 1,
                    "name": "Сукня",
                    "price": 100,
                    "photo_url": "https://example.com/p.jpg",
                }
            )
        ],
        metadata=Metadata(current_state="STATE_4_OFFER", intent="DISCOVERY_OR_QUESTION"),
    )

    # Sync (response mode)
    sync = ManychatWebhook(store)
    sync_payload = sync._to_manychat_response(agent_response)

    # Async (push mode)
    push_client = DummyPushClient()
    async_svc = ManyChatAsyncService(store, runner=object(), push_client=push_client)
    await async_svc._push_response("u1", agent_response, "instagram")
    assert len(push_client.calls) == 1
    async_call = push_client.calls[0]

    # TEXT must match (first text chunk)
    assert sync_payload["content"]["messages"][0]["type"] == "text"
    assert async_call["messages"][0]["type"] == "text"
    assert sync_payload["content"]["messages"][0]["text"] == async_call["messages"][0]["text"]

    # Fields must match
    assert sync_payload["set_field_values"] == async_call["set_field_values"]

    # Tags must match
    assert sync_payload["add_tag"] == async_call["add_tags"]
    assert sync_payload["remove_tag"] == async_call["remove_tags"]

    # Intentional allowed drift:
    # - Sync mode may omit product images except PHOTO_IDENT
    # - Async mode may include product images
    # - Async quick replies disabled
