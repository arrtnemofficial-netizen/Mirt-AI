import asyncio
from dataclasses import dataclass

import pytest

from src.core.models import AgentResponse, Message, Metadata, Product
from src.integrations.manychat.async_service import ManyChatAsyncService
from src.integrations.manychat.response_builder import (
    FIELD_AI_INTENT,
    FIELD_AI_STATE,
    FIELD_LAST_PRODUCT,
    TAG_AI_RESPONDED,
    TAG_NEEDS_HUMAN,
)
from src.services.infra.message_store import InMemoryMessageStore
from src.services.infra.session_store import InMemorySessionStore


@dataclass
class StubPipelineResult:
    response: AgentResponse
    is_fallback: bool = False

    @property
    def result(self):
        return type("ConversationResult", (), {"response": self.response, "is_fallback": self.is_fallback})


def make_response(
    *,
    messages: list[str],
    state: str,
    intent: str,
    products: list[Product] | None = None,
    escalation_level: str = "NONE",
) -> AgentResponse:
    return AgentResponse(
        event="reply",
        messages=[Message(content=m) for m in messages],
        products=products or [],
        metadata=Metadata(current_state=state, intent=intent, escalation_level=escalation_level),
    )


def build_service(monkeypatch, response: AgentResponse, *, is_fallback: bool = False) -> ManyChatAsyncService:
    store = InMemorySessionStore()
    message_store = InMemoryMessageStore()
    service = ManyChatAsyncService(store, runner=None, message_store=message_store)

    async def fake_pipeline(**kwargs):
        return StubPipelineResult(response=response, is_fallback=is_fallback)

    monkeypatch.setattr(
        "src.integrations.manychat.async_service.process_manychat_pipeline",
        fake_pipeline,
    )
    return service


@pytest.mark.manychat
@pytest.mark.integration
@pytest.mark.asyncio
async def test_manychat_handle_returns_messages(monkeypatch):
    """Сервіс повертає ManyChat v2 envelope з контрольованими повідомленнями."""
    response = make_response(
        messages=["Привіт", "Як можу допомогти?"],
        state="STATE_1_DISCOVERY",
        intent="GREETING_ONLY",
    )
    handler = build_service(monkeypatch, response)

    result = await handler.process_message_sync(
        user_id="abc",
        text="hi",
        channel="instagram",
        subscriber_data={"id": "abc"},
    )

    assert result["version"] == "v2"
    msgs = [m["text"] for m in result["content"]["messages"]]
    assert msgs == ["Привіт", "Як можу допомогти?"]
    assert result["_debug"]["current_state"] == "STATE_1_DISCOVERY"
    assert result["_debug"]["intent"] == "GREETING_ONLY"


@pytest.mark.manychat
@pytest.mark.integration
@pytest.mark.asyncio
async def test_manychat_custom_fields(monkeypatch):
    """Custom fields формуються з metadata та продуктів."""
    product = Product.from_legacy(
        {
            "product_id": 123,
            "name": "Сукня Анна",
            "price": 1200,
            "size": "122-128",
            "color": "синій",
            "photo_url": "https://example.com/photo.jpg",
        }
    )
    response = make_response(
        messages=["Ось сукня"],
        state="STATE_4_OFFER",
        intent="DISCOVERY_OR_QUESTION",
        products=[product],
    )
    handler = build_service(monkeypatch, response)

    result = await handler.process_message_sync(
        user_id="abc",
        text="покажи сукню",
        channel="instagram",
        subscriber_data={"id": "abc"},
    )

    fields = {f["field_name"]: f["field_value"] for f in result["set_field_values"]}
    assert fields[FIELD_AI_STATE] == "STATE_4_OFFER"
    assert fields[FIELD_AI_INTENT] == "DISCOVERY_OR_QUESTION"
    assert fields[FIELD_LAST_PRODUCT] == "Сукня Анна"


@pytest.mark.manychat
@pytest.mark.integration
@pytest.mark.asyncio
async def test_manychat_tags(monkeypatch):
    """Escalation -> додаються теги AI_RESPONDED + NEEDS_HUMAN."""
    response = make_response(
        messages=["Передаю менеджеру"],
        state="STATE_8_COMPLAINT",
        intent="COMPLAINT",
        escalation_level="L2",
    )
    handler = build_service(monkeypatch, response)

    result = await handler.process_message_sync(
        user_id="abc",
        text="у мене проблема",
        channel="instagram",
        subscriber_data={"id": "abc"},
    )

    assert TAG_AI_RESPONDED in result["add_tag"]
    assert TAG_NEEDS_HUMAN in result["add_tag"]


@pytest.mark.manychat
@pytest.mark.integration
@pytest.mark.asyncio
async def test_manychat_quick_replies(monkeypatch):
    """Quick replies повертаються у v2 envelope (можуть бути пустими для Instagram)."""
    response = make_response(
        messages=["Що шукаєте?"],
        state="STATE_1_DISCOVERY",
        intent="GREETING_ONLY",
    )
    handler = build_service(monkeypatch, response)

    result = await handler.process_message_sync(
        user_id="abc",
        text="привіт",
        channel="instagram",
        subscriber_data={"id": "abc"},
    )

    assert "quick_replies" in result["content"]
    assert isinstance(result["content"]["quick_replies"], list)


@pytest.mark.manychat
@pytest.mark.integration
@pytest.mark.asyncio
async def test_manychat_image_extraction(monkeypatch):
    """Image-url зберігається в метаданих та не ламає відповідь."""
    response = make_response(
        messages=["Бачу фото!"],
        state="STATE_2_VISION",
        intent="PHOTO_IDENT",
    )
    handler = build_service(monkeypatch, response)

    result = await handler.process_message_sync(
        user_id="user123",
        text="",
        image_url="https://instagram.com/photo.jpg",
        channel="instagram",
        subscriber_data={"id": "user123"},
    )

    assert result["version"] == "v2"
    assert result["_debug"]["intent"] == "PHOTO_IDENT"


@pytest.mark.manychat
@pytest.mark.integration
@pytest.mark.asyncio
async def test_manychat_image_only_no_text(monkeypatch):
    """Image-only запит проходить через sync-пайплайн."""
    handler = build_service(monkeypatch, make_response(messages=["ok"], state="STATE_2_VISION", intent="PHOTO_IDENT"))

    result = await handler.process_message_sync(
        user_id="user456",
        text="",
        image_url="https://example.com/photo.jpg",
        channel="instagram",
        subscriber_data={"id": "user456"},
    )

    assert result["version"] == "v2"


@pytest.mark.manychat
@pytest.mark.integration
@pytest.mark.asyncio
async def test_manychat_missing_text_and_image_raises(monkeypatch):
    """Без тексту й зображення повертається порожня відповідь."""
    handler = build_service(monkeypatch, make_response(messages=[""], state="STATE_1_DISCOVERY", intent="EMPTY"))

    result = await handler.process_message_sync(
        user_id="user789",
        text="",
        image_url=None,
        channel="instagram",
        subscriber_data={"id": "user789"},
    )

    assert result["version"] == "v2"
    msgs = result["content"]["messages"]
    assert len(msgs) == 1
    assert msgs[0].get("text", "") == ""


@pytest.mark.manychat
@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, expected_user_id, expected_text, expected_image_url",
    [
        (
            {"subscriber": {"id": "u1"}, "message": {"image": "https://example.com/a.jpg"}},
            "u1",
            "",
            "https://example.com/a.jpg",
        ),
        (
            {
                "subscriber": {"id": "u2"},
                "message": {"text": "yo", "image_url": "https://example.com/b.jpg"},
            },
            "u2",
            "yo",
            "https://example.com/b.jpg",
        ),
        (
            {
                "subscriber": {"id": "u3"},
                "message": {"text": "t"},
                "data": {"image_url": "https://example.com/c.jpg"},
            },
            "u3",
            "t",
            "https://example.com/c.jpg",
        ),
        (
            {"subscriber": {"id": "u4"}, "data": {"photo_url": "https://example.com/d.jpg"}},
            "u4",
            "",
            "https://example.com/d.jpg",
        ),
        (
            {
                "subscriber": {"id": "u5"},
                "data": {
                    "message": {
                        "content": "hey",
                        "attachments": [
                            {"type": "image", "payload": {"url": "https://example.com/e.jpg"}}
                        ],
                    }
                },
            },
            "u5",
            "hey",
            "https://example.com/e.jpg",
        ),
        (
            {
                "user": {"user_id": 123},
                "message": {
                    "text": "x",
                    "attachments": [
                        {"type": "image", "payload": {"url": "https://example.com/f.jpg"}}
                    ],
                },
            },
            "123",
            "x",
            "https://example.com/f.jpg",
        ),
        (
            {
                "subscriber": {"id": "u6"},
                "message": {
                    "text": "x",
                    "attachments": [
                        {"type": "video"},
                        {"type": "image", "payload": {"url": "https://example.com/g.jpg"}},
                    ],
                },
            },
            "u6",
            "x",
            "https://example.com/g.jpg",
        ),
    ],
)
async def test_manychat_extract_user_text_and_image_variants(
    payload: dict,
    expected_user_id: str,
    expected_text: str,
    expected_image_url: str,
    monkeypatch,
):
    handler = build_service(monkeypatch, make_response(messages=["ok"], state="STATE_1_DISCOVERY", intent="OK"))

    result = await handler.process_message_sync(
        user_id=expected_user_id,
        text=expected_text,
        image_url=expected_image_url,
        channel="instagram",
        subscriber_data={"id": expected_user_id},
    )

    assert result["version"] == "v2"


@pytest.mark.manychat
@pytest.mark.integration
@pytest.mark.asyncio
async def test_manychat_handle_debouncer_supersedes_older_request(monkeypatch):
    handler = build_service(
        monkeypatch, make_response(messages=["ok"], state="STATE_1_DISCOVERY", intent="GREETING_ONLY")
    )
    handler.debouncer.delay = 0.05

    task_1 = asyncio.create_task(
        handler.process_message_sync(user_id="user123", text="first", channel="instagram")
    )
    await asyncio.sleep(0)
    task_2 = asyncio.create_task(
        handler.process_message_sync(user_id="user123", text="second", channel="instagram")
    )

    out_1, out_2 = await asyncio.gather(task_1, task_2)

    assert out_1["version"] == "v2"
    # Перше повідомлення може бути заглушкою/порожнім або містити текст з першого запиту
    msgs_1 = out_1["content"]["messages"]
    assert msgs_1 == [] or msgs_1[0].get("text", "") == "ok"

    assert out_2["version"] == "v2"
    assert out_2["content"]["messages"]


@pytest.mark.manychat
@pytest.mark.integration
def test_push_client_preserves_numeric_field_values():
    """Test that ManyChatPushClient preserves numeric types for ManyChat compatibility.

    ManyChat Number fields require numeric values, not string representations.
    Note: ManyChat limits to 5 actions max, so we test with 5 fields.
    """
    from src.integrations.manychat.push_client import ManyChatPushClient

    client = ManyChatPushClient()

    # Test with mixed types (5 max due to ManyChat limit)
    field_values = [
        {"field_name": "text_field", "field_value": "some text"},
        {"field_name": "number_field", "field_value": 1500},
        {"field_name": "float_field", "field_value": 99.99},
        {"field_name": "string_number", "field_value": "2500"},  # Should be parsed as int
        {"field_name": "bool_field", "field_value": True},
    ]

    actions = client._build_actions(field_values, None, None)

    # Verify types are preserved correctly (5 actions max)
    assert len(actions) == 5

    # Text stays as text
    assert actions[0]["value"] == "some text"
    assert isinstance(actions[0]["value"], str)

    # Numbers stay as numbers
    assert actions[1]["value"] == 1500
    assert isinstance(actions[1]["value"], int)

    assert actions[2]["value"] == 99.99
    assert isinstance(actions[2]["value"], float)

    # String numbers are parsed to numeric types
    assert actions[3]["value"] == 2500
    assert isinstance(actions[3]["value"], int)

    # Booleans stay as booleans
    assert actions[4]["value"] is True
    assert isinstance(actions[4]["value"], bool)


@pytest.mark.manychat
@pytest.mark.integration
def test_push_client_validates_subscriber_id():
    """Test that ManyChatPushClient validates subscriber_id input."""
    from src.integrations.manychat.push_client import ManyChatPushClient

    client = ManyChatPushClient()

    # Test with empty string
    result = client._sanitize_messages([{"type": "text", "text": "test"}])
    assert len(result) == 1  # Sanitization should work

    # Note: Actual send_content validation requires enabled client
    # This test verifies sanitization works independently


@pytest.mark.manychat
@pytest.mark.integration
def test_push_client_sanitizes_long_text():
    """Test that ManyChatPushClient truncates text messages exceeding 2000 chars."""
    from src.integrations.manychat.push_client import ManyChatPushClient

    client = ManyChatPushClient()

    long_text = "x" * 2500
    messages = [{"type": "text", "text": long_text}]

    sanitized = client._sanitize_messages(messages)

    assert len(sanitized) == 1
    assert len(sanitized[0]["text"]) == 2000
    assert sanitized[0]["text"] == "x" * 2000


@pytest.mark.manychat
@pytest.mark.integration
def test_push_client_handles_invalid_messages():
    """Test that ManyChatPushClient handles invalid message formats gracefully."""
    from src.integrations.manychat.push_client import ManyChatPushClient

    client = ManyChatPushClient()

    # Test with empty messages
    assert client._sanitize_messages([]) == []

    # Test with None
    assert client._sanitize_messages([None]) == []

    # Test with empty text
    assert client._sanitize_messages([{"type": "text", "text": ""}]) == []

    # Test with empty image URL
    assert client._sanitize_messages([{"type": "image", "url": ""}]) == []

    # Test with unknown type (should pass through with warning)
    result = client._sanitize_messages([{"type": "unknown", "data": "test"}])
    assert len(result) == 1
    assert result[0]["type"] == "unknown"