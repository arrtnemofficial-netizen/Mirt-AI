import asyncio

import pytest

from src.core.models import AgentResponse, Message, Metadata
from src.integrations.manychat.pipeline import process_manychat_pipeline
from src.services.conversation import ConversationResult
from src.services.infra.debouncer import BufferedMessage


class FakeDebouncer:
    def __init__(self, result: BufferedMessage | None) -> None:
        self._result = result

    async def wait_for_debounce(self, _session_id: str, _message: BufferedMessage):
        return self._result


class FakeHandler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    async def process_message(self, session_id: str, text: str, *, extra_metadata=None):
        self.calls.append((session_id, text, extra_metadata))
        response = AgentResponse(
            event="reply",
            messages=[Message(type="text", content="ok")],
            metadata=Metadata(session_id=session_id, current_state="STATE_0_INIT"),
        )
        return ConversationResult(response=response, state={}, error=None, is_fallback=False)


@pytest.mark.asyncio
async def test_pipeline_superseded_calls_hook_and_returns_none():
    handler = FakeHandler()
    debouncer = FakeDebouncer(result=None)
    superseded_called = {"value": False}

    def _on_superseded() -> None:
        superseded_called["value"] = True

    result = await process_manychat_pipeline(
        handler=handler,
        debouncer=debouncer,  # type: ignore[arg-type]
        user_id="u1",
        text="hello",
        image_url=None,
        extra_metadata=None,
        on_superseded=_on_superseded,
    )

    assert result is None
    assert superseded_called["value"] is True
    assert handler.calls == []


@pytest.mark.asyncio
async def test_pipeline_debounced_calls_handler_and_emits_hook():
    handler = FakeHandler()
    debounced = {"has_image": None, "text": None}
    buffered = BufferedMessage(
        text="Hi",
        has_image=False,
        image_url=None,
        extra_metadata={"has_image": True},
    )
    debouncer = FakeDebouncer(result=buffered)

    def _on_debounced(
        _aggregated_msg: BufferedMessage,
        has_image: bool,
        final_text: str,
        _final_metadata: dict | None,
    ) -> None:
        debounced["has_image"] = has_image
        debounced["text"] = final_text

    result = await process_manychat_pipeline(
        handler=handler,
        debouncer=debouncer,  # type: ignore[arg-type]
        user_id="u2",
        text="ignored",
        image_url=None,
        extra_metadata={"trace_id": "t1"},
        on_debounced=_on_debounced,
    )

    assert result is not None
    assert debounced["has_image"] is True
    assert debounced["text"] == "Hi"
    assert handler.calls == [("u2", "Hi", {"has_image": True})]


@pytest.mark.asyncio
async def test_pipeline_timeout_raises():
    class HangingHandler(FakeHandler):
        async def process_message(self, session_id: str, text: str, *, extra_metadata=None):
            # Hang forever without sleeping (simulate stuck process)
            await asyncio.Future()

    handler = HangingHandler()
    buffered = BufferedMessage(text="Hi", has_image=False, image_url=None, extra_metadata={})
    debouncer = FakeDebouncer(result=buffered)

    with pytest.raises(TimeoutError):
        await process_manychat_pipeline(
            handler=handler,
            debouncer=debouncer,  # type: ignore[arg-type]
            user_id="u3",
            text="Hi",
            image_url=None,
            extra_metadata={},
            time_budget_provider=lambda _has_image: 0.001,
        )
