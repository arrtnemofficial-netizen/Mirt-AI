"""Session store primitives for chat platforms."""
from __future__ import annotations

from copy import deepcopy
from typing import Dict, Protocol

from src.agents.graph import AgentState


class SessionStore(Protocol):
    """Contract for session storage implementations."""

    def get(self, session_id: str) -> AgentState:
        """Return stored state or a fresh empty state."""

    def save(self, session_id: str, state: AgentState) -> None:
        """Persist the current state for the session."""


class InMemorySessionStore:
    """Lightweight, process-local session storage.

    Suitable for demos and single-process deployments. Replace with Redis/DB for scale.
    """

    def __init__(self) -> None:
        self._store: Dict[str, AgentState] = {}

    def get(self, session_id: str) -> AgentState:
        """Return stored state or a fresh empty state."""

        existing = self._store.get(session_id)
        if existing:
            return deepcopy(existing)
        return AgentState(messages=[], metadata={}, current_state="STATE0_INIT")

    def save(self, session_id: str, state: AgentState) -> None:
        """Persist the current state for the session."""

        self._store[session_id] = deepcopy(state)


def state_from_text(text: str, session_id: str) -> AgentState:
    """Helper to bootstrap state from a single user message."""

    return AgentState(
        messages=[{"role": "user", "content": text}],
        metadata={"session_id": session_id},
        current_state="STATE0_INIT",
    )
