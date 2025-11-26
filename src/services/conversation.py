"""Centralized conversation handling with error management.

This module eliminates code duplication between Telegram and ManyChat handlers
by providing a single ConversationHandler that manages the full message lifecycle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from src.agents.nodes import ConversationState
from src.core.constants import AgentState as StateEnum, MessageTag
from src.core.models import AgentResponse, Escalation, Message, Metadata
from src.services.message_store import MessageStore, StoredMessage
from src.services.session_store import SessionStore

logger = logging.getLogger(__name__)


class ConversationError(Exception):
    """Base exception for conversation processing errors."""

    def __init__(self, message: str, session_id: str, recoverable: bool = True):
        super().__init__(message)
        self.session_id = session_id
        self.recoverable = recoverable


class AgentInvocationError(ConversationError):
    """Raised when the AI agent fails to process a message."""
    pass


class ResponseParsingError(ConversationError):
    """Raised when the agent response cannot be parsed."""
    pass


class GraphRunner(Protocol):
    """Protocol for LangGraph runner compatibility."""

    async def ainvoke(self, state: ConversationState) -> ConversationState:
        ...


@dataclass
class ConversationResult:
    """Result of processing a user message."""

    response: AgentResponse
    state: ConversationState
    error: Optional[str] = None
    is_fallback: bool = False


@dataclass
class ConversationHandler:
    """Centralized handler for all conversation platforms.

    Provides unified message processing with:
    - Proper error handling and graceful fallbacks
    - Message persistence to MessageStore
    - Session state management
    - Consistent tagging for escalations
    """

    session_store: SessionStore
    message_store: MessageStore
    runner: GraphRunner
    fallback_message: str = field(
        default="Вибачте, сталася технічна помилка. Спробуйте ще раз або зверніться до підтримки."
    )

    async def process_message(
        self,
        session_id: str,
        text: str,
        *,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> ConversationResult:
        """Process a user message through the full conversation pipeline.

        Args:
            session_id: Unique identifier for the conversation session
            text: User message text
            extra_metadata: Additional metadata to include in the state

        Returns:
            ConversationResult with the agent response and updated state

        This method never raises exceptions to the caller - all errors are
        caught and converted to graceful fallback responses.
        """
        state: Optional[ConversationState] = None

        try:
            # Load or create session state
            state = self.session_store.get(session_id)
            state["messages"].append({"role": "user", "content": text})
            state["metadata"].setdefault("session_id", session_id)
            if extra_metadata:
                state["metadata"].update(extra_metadata)

            # Persist user message
            self._persist_user_message(session_id, text)

            # Invoke the agent
            result_state = await self._invoke_agent(state)

            # Parse response
            agent_response = self._parse_response(result_state, session_id)

            # Persist assistant response
            self._persist_assistant_message(session_id, agent_response)

            # Save updated state
            self.session_store.save(session_id, result_state)

            return ConversationResult(
                response=agent_response,
                state=result_state,
            )

        except ConversationError as e:
            logger.error(
                "Conversation error for session %s: %s (recoverable=%s)",
                session_id,
                str(e),
                e.recoverable,
            )
            return self._build_fallback_result(session_id, state, str(e))

        except Exception as e:
            logger.exception(
                "Unexpected error processing message for session %s",
                session_id,
            )
            return self._build_fallback_result(session_id, state, str(e))

    async def _invoke_agent(self, state: ConversationState) -> ConversationState:
        """Invoke the LangGraph agent with error handling."""
        try:
            return await self.runner.ainvoke(state)
        except Exception as e:
            raise AgentInvocationError(
                f"Agent invocation failed: {e}",
                session_id=state.get("metadata", {}).get("session_id", "unknown"),
            ) from e

    def _parse_response(
        self, result_state: ConversationState, session_id: str
    ) -> AgentResponse:
        """Parse the agent response from the result state."""
        messages = result_state.get("messages", [])

        if not messages:
            raise ResponseParsingError(
                "No messages in result state",
                session_id=session_id,
            )

        last_message = messages[-1]
        content = last_message.get("content", "")

        if not content:
            raise ResponseParsingError(
                "Empty content in last message",
                session_id=session_id,
            )

        try:
            return AgentResponse.model_validate_json(content)
        except Exception as e:
            raise ResponseParsingError(
                f"Failed to parse agent response: {e}",
                session_id=session_id,
            ) from e

    def _persist_user_message(self, session_id: str, text: str) -> None:
        """Store the user message in the message store."""
        try:
            self.message_store.append(
                StoredMessage(session_id=session_id, role="user", content=text)
            )
        except Exception as e:
            logger.warning(
                "Failed to persist user message for session %s: %s",
                session_id,
                e,
            )

    def _persist_assistant_message(
        self, session_id: str, response: AgentResponse
    ) -> None:
        """Store the assistant response with appropriate tags."""
        try:
            tags = [MessageTag.HUMAN_NEEDED] if response.escalation else []
            self.message_store.append(
                StoredMessage(
                    session_id=session_id,
                    role="assistant",
                    content=response.model_dump_json(),
                    tags=tags,
                )
            )
        except Exception as e:
            logger.warning(
                "Failed to persist assistant message for session %s: %s",
                session_id,
                e,
            )

    def _build_fallback_result(
        self,
        session_id: str,
        state: Optional[ConversationState],
        error_message: str,
    ) -> ConversationResult:
        """Build a graceful fallback response when processing fails."""
        current_state = StateEnum.default()
        if state:
            current_state = state.get("current_state", StateEnum.default())

        fallback_response = AgentResponse(
            event="escalation",
            messages=[Message(content=self.fallback_message)],
            products=[],
            metadata=Metadata(
                session_id=session_id,
                current_state=current_state,
                event_trigger="error_fallback",
                notes=f"Error: {error_message[:200]}",
            ),
            escalation=Escalation(
                level="L2",
                reason=f"Technical error: {error_message[:100]}",
                target="technical_support",
            ),
        )

        # Try to persist the fallback response
        self._persist_assistant_message(session_id, fallback_response)

        # Build minimal state if we don't have one
        fallback_state: ConversationState = state or ConversationState(
            messages=[],
            metadata={"session_id": session_id},
            current_state=current_state,
        )

        return ConversationResult(
            response=fallback_response,
            state=fallback_state,
            error=error_message,
            is_fallback=True,
        )


def create_conversation_handler(
    session_store: SessionStore,
    message_store: MessageStore,
    runner: GraphRunner,
    fallback_message: Optional[str] = None,
) -> ConversationHandler:
    """Factory function to create a ConversationHandler with dependencies."""
    kwargs: dict[str, Any] = {
        "session_store": session_store,
        "message_store": message_store,
        "runner": runner,
    }
    if fallback_message:
        kwargs["fallback_message"] = fallback_message

    return ConversationHandler(**kwargs)
