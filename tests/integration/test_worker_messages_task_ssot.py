from __future__ import annotations

from typing import Any


class _DummyMessageStore:
    def __init__(self) -> None:
        self._messages: list[Any] = []

    def append(self, message: Any) -> None:
        self._messages.append(message)

    def list(self, session_id: str, limit: int = 20) -> list[Any]:
        return [m for m in self._messages if m.session_id == session_id][-limit:]


class _DummyGraph:
    pass


def test_process_message_builds_ssot_state_and_uses_session_thread_id(monkeypatch):
    from src.workers.tasks import messages as worker_messages

    captured: dict[str, Any] = {}
    store = _DummyMessageStore()

    async def _fake_invoke_graph(*, state, session_id, graph):
        captured["state"] = state
        captured["session_id"] = session_id
        captured["graph"] = graph
        return {
            "messages": [{"role": "assistant", "content": "ok"}],
            "session_id": session_id,
            "metadata": state.get("metadata", {}),
        }

    monkeypatch.setattr(worker_messages, "run_sync", lambda coro: __import__("asyncio").run(coro))
    monkeypatch.setattr("src.services.storage.create_message_store", lambda: store)
    monkeypatch.setattr("src.agents.get_active_graph", lambda: _DummyGraph())
    monkeypatch.setattr("src.agents.langgraph.graph.invoke_graph", _fake_invoke_graph)

    result = worker_messages.process_message.run(
        session_id="sess-123",
        user_message="Привіт",
        user_id="u-1",
        platform="telegram",
        chat_id="chat-9",
        message_id="msg-7",
        metadata={"locale": "uk", "campaign": "spring"},
    )

    assert result["status"] == "success"
    assert captured["session_id"] == "sess-123"

    state = captured["state"]
    metadata = state["metadata"]

    # SSOT core keys from StateSchema/create_initial_state
    for key in ("session_id", "thread_id", "messages", "metadata", "current_state", "dialog_phase"):
        assert key in state, f"Missing SSOT key: {key}"

    # Checkpointer consistency contract
    assert state["session_id"] == "sess-123"
    assert state["thread_id"] == "sess-123"

    # Unified context→metadata mapping
    assert metadata["session_id"] == "sess-123"
    assert metadata["user_id"] == "u-1"
    assert metadata["platform"] == "telegram"
    assert metadata["chat_id"] == "chat-9"
    assert metadata["message_id"] == "msg-7"
    assert metadata["locale"] == "uk"
    assert metadata["campaign"] == "spring"
    assert "context" not in state
