"""Session store primitives for chat platforms."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from langchain_core.messages import BaseMessage

from src.core.conversation_state import ConversationState
from src.core.constants import AgentState as StateEnum


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
        return ConversationState(messages=[], metadata={}, current_state=StateEnum.default())

    def save(self, session_id: str, state: ConversationState) -> None:
        """Persist the current state for the session."""

        # Serialize state to handle LangChain Message objects
        serialized_state = _serialize_for_json(dict(state))
        self._store[session_id] = deepcopy(serialized_state)


def state_from_text(text: str, session_id: str) -> ConversationState:
    """Helper to bootstrap state from a single user message."""

    return ConversationState(
        messages=[{"role": "user", "content": text}],
        metadata={"session_id": session_id},
        current_state=StateEnum.default(),
    )

