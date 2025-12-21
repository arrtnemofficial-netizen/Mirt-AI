"""Conversation models and protocols.

Contains data structures used by ConversationHandler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.agents import ConversationState
    from src.core.models import AgentResponse


class TransitionResult:
    """Stub for validate_state_transition result.

    In NEW architecture: LangGraph edges make invalid transitions impossible.
    This stub exists for legacy compatibility.
    """

    def __init__(self, new_state: str, was_corrected: bool = False, reason: str | None = None):
        self.new_state = new_state
        self.was_corrected = was_corrected
        self.reason = reason


class GraphRunner(Protocol):
    """Protocol for LangGraph runner compatibility."""

    async def ainvoke(
        self, state: "ConversationState", config: dict[str, Any] | None = None
    ) -> "ConversationState": ...


@dataclass
class ConversationResult:
    """Result of processing a user message."""

    response: "AgentResponse"
    state: "ConversationState"
    error: str | None = None
    is_fallback: bool = False
