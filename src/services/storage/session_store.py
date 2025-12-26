"""Session store primitives for chat platforms."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Protocol

from langchain_core.messages import BaseMessage

from src.core.constants import AgentState as StateEnum

if TYPE_CHECKING:
    from src.agents import ConversationState

def _serialize_for_json(value: Any) -> Any:
    """Recursively serialize values, converting LangChain Message objects to dicts."""
    if isinstance(value, BaseMessage):
        return {
            "type": value.type,
            "content": value.content,
            "additional_kwargs": getattr(value, "additional_kwargs", {}),
        }
    elif isinstance(value, dict):
        return {k: _serialize_for_json(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_serialize_for_json(item) for item in value]
    else:
        return value


class SessionStore(Protocol):
    """Contract for session storage implementations."""

    def get(self, session_id: str) -> ConversationState:
        """Return stored state or a fresh empty state."""

    def save(self, session_id: str, state: ConversationState) -> None:
        """Persist the current state for the session."""

    def delete(self, session_id: str) -> bool:
        """Delete session state. Returns True if session existed."""


class InMemorySessionStore:
    """Lightweight, process-local session storage.

    Suitable for demos and single-process deployments. Replace with Redis/DB for scale.
    """

    def __init__(self) -> None:
        self._store: dict[str, ConversationState] = {}

    def get(self, session_id: str) -> ConversationState:
        """Return stored state or a fresh empty state."""

        existing = self._store.get(session_id)
        if existing:
            return deepcopy(existing)
        from src.agents import ConversationState

        return ConversationState(messages=[], metadata={}, current_state=StateEnum.default())

    def save(self, session_id: str, state: ConversationState) -> None:
        """Persist the current state for the session."""

        # Serialize state to handle LangChain Message objects
        serialized_state = _serialize_for_json(dict(state))
        self._store[session_id] = deepcopy(serialized_state)

    def delete(self, session_id: str) -> bool:
        """Delete session state. Returns True if session existed."""
        if session_id in self._store:
            del self._store[session_id]
            return True
        return False


def state_from_text(text: str, session_id: str) -> ConversationState:
    """Helper to bootstrap state from a single user message."""

    from src.agents import ConversationState

    return ConversationState(
        messages=[{"role": "user", "content": text}],
        metadata={"session_id": session_id},
        current_state=StateEnum.default(),
    )
