import pytest
from pydantic import SecretStr
from unittest.mock import AsyncMock
from types import SimpleNamespace

from src.bot import telegram_bot
from src.bot.telegram_bot import _dispatch_to_telegram, build_dispatcher
from src.core.models import AgentResponse, Message, Metadata, Product
from src.services.message_store import InMemoryMessageStore, StoredMessage
from src.services.session_store import InMemorySessionStore


pytestmark = [pytest.mark.telegram]


class DummyRunner:
    async def ainvoke(self, state, config=None):
        return state


class DummyChat:
    def __init__(self, chat_id: int):
        self.id = chat_id


class DummyMessage:
    def __init__(self, chat_id: int = 123):
        self.chat = DummyChat(chat_id)
        self.text = None
        self.caption = None
        self.photo = []
        self.bot = None
        self.answer = AsyncMock()
        self.answer_photo = AsyncMock()
        self.from_user = None


@pytest.mark.asyncio
async def test_dispatch_to_telegram_sends_text_without_reply_markup():
    msg = DummyMessage()

    agent_response = AgentResponse(
        event="simple_answer",
        messages=[Message(content="Hello"), Message(content="World")],
        products=[],
        metadata=Metadata(current_state="STATE_1_DISCOVERY", intent="GREETING_ONLY"),
    )

    await _dispatch_to_telegram(msg, agent_response, session_id="s")

    assert msg.answer.await_count == 2
    for call in msg.answer.await_args_list:
        assert call.kwargs == {}
    msg.answer_photo.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_to_telegram_sends_photos_only_for_photo_ident():
    msg = DummyMessage()

    agent_response = AgentResponse(
        event="simple_answer",
        messages=[Message(content="Ok")],
        products=[
            Product(
                id=1,
                name="Тест",
                price=1,
                photo_url="https://example.com/p.jpg",
            )
        ],
        metadata=Metadata(current_state="STATE_2_VISION", intent="PHOTO_IDENT"),
    )

    await _dispatch_to_telegram(msg, agent_response, session_id="s")

    assert msg.answer.await_count == 1
    assert msg.answer_photo.await_count == 1

    photo_call = msg.answer_photo.await_args_list[0]
    assert photo_call.kwargs["photo"] == "https://example.com/p.jpg"
    assert photo_call.kwargs["caption"] == ""
    assert "reply_markup" not in photo_call.kwargs


@pytest.mark.asyncio
async def test_start_and_restart_reset_session_and_clear_message_history():
    store = InMemorySessionStore()
    msg_store = InMemoryMessageStore()

    dp = build_dispatcher(store, msg_store, runner=DummyRunner())
    start_handler = dp.message.handlers[0].callback
    restart_handler = dp.message.handlers[1].callback

    message = DummyMessage(chat_id=123)

    await start_handler(message)

    state = store.get("123")
    assert state["current_state"] == "STATE_0_INIT"
    assert state["step_number"] == 0

    assert message.answer.await_count == 1
    assert "Можемо почати" in message.answer.await_args_list[0].args[0]

    msg_store.append(StoredMessage(session_id="123", role="user", content="hi"))
    assert msg_store.list("123")

    message.answer.reset_mock()

    await restart_handler(message)

    state2 = store.get("123")
    assert state2["current_state"] == "STATE_0_INIT"
    assert state2["step_number"] == 0

    assert msg_store.list("123") == []

    assert message.answer.await_count == 1
    assert "Сесію" in message.answer.await_args_list[0].args[0]


@pytest.mark.asyncio
async def test_text_handler_delegates_to_debouncer(monkeypatch: pytest.MonkeyPatch):
    store = InMemorySessionStore()
    msg_store = InMemoryMessageStore()

    process_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(telegram_bot, "_process_incoming_debounced", process_mock)

    dp = build_dispatcher(store, msg_store, runner=DummyRunner())
    text_handler = dp.message.handlers[2].callback

    message = DummyMessage(chat_id=123)
    message.text = "hi"

    await text_handler(message)

    assert process_mock.await_count == 1
    assert process_mock.await_args.args[0] is message


@pytest.mark.asyncio
async def test_photo_handler_builds_telegram_file_url_and_delegates(monkeypatch: pytest.MonkeyPatch):
    store = InMemorySessionStore()
    msg_store = InMemoryMessageStore()

    process_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(telegram_bot, "_process_incoming_debounced", process_mock)

    monkeypatch.setattr(telegram_bot.settings, "TELEGRAM_BOT_TOKEN", SecretStr("TESTTOKEN"))

    dp = build_dispatcher(store, msg_store, runner=DummyRunner())
    photo_handler = dp.message.handlers[3].callback

    message = DummyMessage(chat_id=123)
    message.caption = "desc"

    photo = SimpleNamespace(file_id="file123")
    message.photo = [photo]

    bot = SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path="photos/p.jpg")))
    message.bot = bot

    await photo_handler(message)

    assert process_mock.await_count == 1

    kwargs = process_mock.await_args.kwargs
    assert kwargs["override_text"] == "desc"
    assert kwargs["has_image"] is True
    assert kwargs["image_url"] == "https://api.telegram.org/file/botTESTTOKEN/photos/p.jpg"
