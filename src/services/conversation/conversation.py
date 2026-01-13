"""Centralized conversation handling with error management.

This module eliminates code duplication between Telegram and ManyChat handlers
by providing a single ConversationHandler that manages the full message lifecycle.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from src.core.models import BaseConversationState as ConversationState

from src.conf.config import settings
from src.core.constants import AgentState as StateEnum
from src.core.constants import MessageTag
from src.core.debug_logger import debug_log
from src.core.models import AgentResponse, Escalation, Message, Metadata, Product
from src.services.observability import track_metric
from src.services.storage import MessageStore, StoredMessage
from src.services.guardrails.loop_detector import apply_loop_protection
from src.services.parser.output_parser import parse_llm_output, convert_support_response
from src.services.session.manager import SessionManager


# =============================================================================
# STUB FUNCTIONS (replacing deleted output_parser.py and state_validator.py)
# In NEW architecture: PydanticAI handles parsing, LangGraph handles transitions
# =============================================================================





if TYPE_CHECKING:
    from src.services.storage import SessionStore


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

    async def ainvoke(
        self, state: ConversationState, config: dict[str, Any] | None = None
    ) -> ConversationState: ...


@dataclass
class ConversationResult:
    """Result of processing a user message."""

    response: AgentResponse
    state: ConversationState
    error: str | None = None
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
    fallback_message: str = field(default="")  # Will use human_responses dynamically
    max_retries: int = field(default=2)
    retry_delay: float = field(default=1.0)
    _bg_tasks: set[asyncio.Task] = field(default_factory=set)

    def __post_init__(self):
        self.session_manager = SessionManager(self.session_store)

    def _get_fallback(self) -> str:
        from src.core.human_responses import get_human_response

        return get_human_response("timeout")

    async def process_message(
        self,
        session_id: str,
        text: str,
        *,
        extra_metadata: dict[str, Any] | None = None,
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
        state: ConversationState | None = None
        import time as _time

        _proc_start = _time.time()

        try:
            # SECURITY: Sanitize input against prompt injection
            from src.core.input_sanitizer import process_user_message

            text, was_sanitized = process_user_message(text)
            if was_sanitized:
                logger.warning("[SECURITY] Message sanitized for session %s", session_id)

            # Load or create session state (delegated to SessionManager)
            state = await self.session_manager.load_session(
                session_id=session_id,
                extra_metadata=extra_metadata
            )

            # Append current user message to state
            state["messages"].append({"role": "user", "content": text})

            # DEBUG: Log request start
            if settings.DEBUG_TRACE_LOGS:
                debug_log.request_start(
                    session_id=session_id,
                    user_message=text,
                    has_image=state.get("has_image", False),
                    metadata=state.get("metadata"),
                )

            # Persist user message (with user_id from metadata)
            self._persist_user_message(session_id, text, state.get("metadata"))

            # SITNIKS FIRST TOUCH (on first message, independent of memory gating)
            # This ensures sitniks_chat_mappings is always populated when usernames are available
            metadata = state.get("metadata", {})
            step_number = state.get("step_number", 0)
            if step_number <= 1:
                instagram_username = metadata.get("instagram_username")
                telegram_username = metadata.get("telegram_username") or metadata.get("user_nickname")

                if instagram_username or telegram_username:
                    try:
                        from src.integrations.crm.sitniks_chat_service import (
                            get_sitniks_chat_service,
                        )
                        sitniks_service = get_sitniks_chat_service()
                        if sitniks_service.enabled:
                            sitniks_result = await sitniks_service.handle_first_touch(
                                user_id=session_id,
                                instagram_username=instagram_username,
                                telegram_username=telegram_username,
                            )
                            if sitniks_result.get("success"):
                                logger.info(
                                    "[SESSION %s] Sitniks first touch completed: chat_id=%s",
                                    session_id,
                                    sitniks_result.get("chat_id"),
                                )
                                # Store chat_id in state metadata for later use
                                state["metadata"]["sitniks_chat_id"] = sitniks_result.get("chat_id")
                                state["metadata"]["sitniks_first_touch_done"] = True
                    except Exception as e:
                        logger.warning("[SESSION %s] Sitniks first touch error: %s", session_id, e)

            # Invoke the agent
            logger.info(
                "[SESSION %s] ⏱️ Starting _invoke_agent (%.2fs since process_message start)",
                session_id,
                _time.time() - _proc_start,
            )
            before_invoke_state = deepcopy(state)
            _invoke_start = _time.time()
            result_state = await self._invoke_agent(state)
            logger.info(
                "[SESSION %s] ⏱️ _invoke_agent took %.2fs", session_id, _time.time() - _invoke_start
            )

            result_state = apply_loop_protection(
                session_id=session_id,
                before_state=before_invoke_state,
                after_state=result_state,
                user_text=text,
            )

            # Parse response
            agent_response = self._parse_response(result_state, session_id)

            # Log outgoing message for snippet verification
            preview_text = ""
            try:
                preview_text = "\n".join(
                    [
                        m.content
                        for m in (agent_response.messages or [])
                        if getattr(m, "content", None)
                    ]
                )
            except Exception:
                preview_text = ""
            logger.info(
                "📤 Outgoing message (state=%s, intent=%s): %s",
                agent_response.metadata.current_state,
                agent_response.metadata.intent,
                preview_text[:200] + "..." if len(preview_text) > 200 else preview_text,
            )

            # Persist assistant response (with user_id from metadata)
            self._persist_assistant_message(session_id, agent_response, result_state.get("metadata"))

            # Save updated state (delegated to SessionManager)
            await self.session_manager.save_session(session_id, result_state)

            # Track end-to-end latency metric
            end_to_end_latency_ms = (_time.time() - _proc_start) * 1000.0
            track_metric(
                "end_to_end_latency_ms",
                end_to_end_latency_ms,
                {
                    "state": agent_response.metadata.current_state,
                    "intent": agent_response.metadata.intent or "unknown",
                },
            )

            # Notify manager for ANY escalation-like outcome.
            # This covers cases where the graph finishes with goto="end" (e.g. payment proof)
            # and therefore does not pass through escalation_node.
            # BUT: Skip if notification was already sent by vision_node or escalation_node
            try:
                # Check if notification was already sent (e.g. by vision_node)
                notification_already_sent = bool(result_state.get("manager_notification_sent", False))

                is_escalation = bool(
                    agent_response.escalation
                    or (agent_response.metadata.escalation_level not in (None, "", "NONE"))
                    or bool(result_state.get("should_escalate"))
                )
                if is_escalation and not notification_already_sent:
                    from src.services.notifications import NotificationService

                    reason = ""
                    if agent_response.escalation and agent_response.escalation.reason:
                        reason = str(agent_response.escalation.reason)
                    elif result_state.get("escalation_reason"):
                        reason = str(result_state.get("escalation_reason") or "")
                    else:
                        reason = "ESCALATION"

                    meta = result_state.get("metadata", {})
                    if not isinstance(meta, dict):
                        meta = {}

                    details: dict[str, Any] = {
                        "trace_id": result_state.get("trace_id"),
                        "dialog_phase": result_state.get("dialog_phase"),
                        "current_state": agent_response.metadata.current_state,
                        "intent": agent_response.metadata.intent,
                        **meta,
                    }

                    # Provide product summary (for manager context)
                    try:
                        details["products"] = [
                            p.model_dump() for p in (agent_response.products or [])
                        ]
                    except Exception:
                        details["products"] = []

                    notifier = NotificationService()
                    await notifier.send_escalation_alert(
                        session_id=session_id,
                        reason=reason,
                        user_context=text,
                        details=details,
                    )
            except Exception as notify_exc:
                logger.warning(
                    "Manager notification failed for session %s: %s",
                    session_id,
                    str(notify_exc)[:200],
                )

            # DEBUG: Log request end
            if settings.DEBUG_TRACE_LOGS:
                debug_log.request_end(
                    session_id=session_id,
                    response_preview=agent_response
                    if isinstance(agent_response, str)
                    else str(agent_response)[:100],
                    final_phase=result_state.get("dialog_phase", "?"),
                    final_state=result_state.get("current_state", "?"),
                )

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
        """Invoke the LangGraph agent with retry logic and thread_id for persistence."""
        import asyncio

        metadata = state.get("metadata", {})
        session_id = metadata.get("session_id", "unknown")
        thread_id = metadata.get("thread_id", session_id)
        last_error: Exception | None = None

        # Use thread_id for LangGraph checkpointer persistence
        config = {"configurable": {"thread_id": thread_id}}

        for attempt in range(self.max_retries + 1):
            try:
                result = await self.runner.ainvoke(state, config=config)
                if attempt > 0:
                    logger.info("Agent succeeded on retry %d for session %s", attempt, session_id)
                return result
            except Exception as e:
                last_error = e
                error_info = f"{type(e).__name__}: {e!s}" if str(e) else type(e).__name__
                if attempt < self.max_retries:
                    logger.warning(
                        "Agent attempt %d failed for session %s: %s. Retrying...",
                        attempt + 1,
                        session_id,
                        error_info[:200],
                    )
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.exception(
                        "Agent failed after %d attempts for session %s: %s",
                        self.max_retries + 1,
                        session_id,
                        error_info,
                    )

        raise AgentInvocationError(
            f"Agent invocation failed after {self.max_retries + 1} attempts: {last_error}",
            session_id=session_id,
        ) from last_error

    def _parse_response(self, result_state: ConversationState, session_id: str) -> AgentResponse:
        """Parse the agent response from the result state with robust fallbacks."""
        agent_response_data = result_state.get("agent_response")
        current_state = result_state.get("current_state", "STATE_0_INIT")

        if agent_response_data:
            try:
                # Convert SupportResponse format to AgentResponse format
                # Key difference: EscalationInfo (no level) vs Escalation (has level)
                return convert_support_response(agent_response_data, session_id)
            except Exception as exc:
                logger.warning(
                    "Failed to parse structured agent response for session %s: %s",
                    session_id,
                    exc,
                )

        messages = result_state.get("messages", [])
        if not messages:
            logger.warning("No messages in result state for session %s", session_id)
            return AgentResponse(
                event="reply",
                messages=[Message(type="text", content="")],
                metadata=Metadata(session_id=session_id, current_state=current_state),
            )

        last_message = messages[-1]
        content = last_message.get("content", "")

        return parse_llm_output(
            content,
            session_id=session_id,
            current_state=current_state,
        )



    def _persist_user_message(
        self, session_id: str, text: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Store the user message in the message store."""
        # Extract user_id from metadata (fallback to session_id if not available)
        user_id = None
        if metadata:
            user_id = metadata.get("user_id") or metadata.get("session_id") or session_id
        else:
            user_id = session_id  # Fallback to session_id

        msg = StoredMessage(
            session_id=session_id,
            role="user",
            content=text,
            user_id=user_id,
            metadata=metadata,  # Pass metadata for users table updates
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                self.message_store.append(msg)
            except Exception as e:
                logger.warning(
                    "Failed to persist user message for session %s: %s",
                    session_id,
                    e,
                )
            return

        async def _bg() -> None:
            try:
                await asyncio.to_thread(self.message_store.append, msg)
            except Exception as e:
                logger.warning(
                    "Failed to persist user message for session %s: %s",
                    session_id,
                    e,
                )

        task = loop.create_task(_bg())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _persist_assistant_message(
        self, session_id: str, response: AgentResponse, metadata: dict[str, Any] | None = None
    ) -> None:
        """Store the assistant response with appropriate tags."""
        # Extract user_id from metadata (fallback to session_id if not available)
        user_id = None
        if metadata:
            user_id = metadata.get("user_id") or metadata.get("session_id") or session_id
        else:
            user_id = session_id  # Fallback to session_id

        tags = [MessageTag.HUMAN_NEEDED] if response.escalation else []
        msg = StoredMessage(
            session_id=session_id,
            role="assistant",
            content=response.model_dump_json(),
            user_id=user_id,
            tags=tags,
            metadata=metadata,  # Pass metadata for users table updates
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                self.message_store.append(msg)
            except Exception as e:
                logger.warning(
                    "Failed to persist assistant message for session %s: %s",
                    session_id,
                    e,
                )
            return

        async def _bg() -> None:
            try:
                await asyncio.to_thread(self.message_store.append, msg)
            except Exception as e:
                logger.warning(
                    "Failed to persist assistant message for session %s: %s",
                    session_id,
                    e,
                )

        task = loop.create_task(_bg())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _build_fallback_result(
        self,
        session_id: str,
        state: ConversationState | None,
        error_message: str,
    ) -> ConversationResult:
        """Build a graceful fallback response when processing fails."""
        current_state = StateEnum.default()
        if state:
            current_state = state.get("current_state", StateEnum.default())

        fallback_text = self.fallback_message or self._get_fallback()
        fallback_response = AgentResponse(
            event="escalation",
            messages=[Message(content=fallback_text)],
            products=[],
            metadata=Metadata(
                session_id=session_id,
                current_state=current_state,
                escalation_level="L2",
                event_trigger="error_fallback",
                notes=f"Error: {error_message[:200]}",
            ),
            escalation=Escalation(
                level="L2",
                reason=f"Technical error: {error_message[:100]}",
                target="technical_support",
            ),
        )

        # Try to persist the fallback response (with user_id from state if available)
        fallback_metadata = state.get("metadata") if state else None
        self._persist_assistant_message(session_id, fallback_response, fallback_metadata)

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
    fallback_message: str | None = None,
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
