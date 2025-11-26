"""Session store primitives for chat platforms."""
from __future__ import annotations

from copy import deepcopy
from typing import Dict, Protocol

from src.agents.nodes import ConversationState
from src.core.constants import AgentState as StateEnum


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
        self._store: Dict[str, ConversationState] = {}

    def get(self, session_id: str) -> ConversationState:
        """Return stored state or a fresh empty state."""

        existing = self._store.get(session_id)
        if existing:
            return deepcopy(existing)
        return ConversationState(messages=[], metadata={}, current_state=StateEnum.default())

    def save(self, session_id: str, state: ConversationState) -> None:
        """Persist the current state for the session."""

        self._store[session_id] = deepcopy(state)


def state_from_text(text: str, session_id: str) -> ConversationState:
    """Helper to bootstrap state from a single user message."""

    return ConversationState(
        messages=[{"role": "user", "content": text}],
        metadata={"session_id": session_id},
        current_state=StateEnum.default(),
    )
