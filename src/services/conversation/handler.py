"""Centralized conversation handling with error management.

This module provides the ConversationHandler class that manages
the full message lifecycle for all conversation platforms.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.core.conversation_state import ConversationState
from src.conf.config import settings
from src.core.constants import AgentState as StateEnum
from src.core.constants import MessageTag
from src.core.debug_logger import debug_log
from src.core.models import AgentResponse, Escalation, Message, Metadata, Product
from src.services.conversation.exceptions import AgentInvocationError, ConversationError
from src.services.conversation.guardrails import apply_transition_guardrails
from src.services.conversation.models import ConversationResult, GraphRunner
from src.services.conversation.parser import parse_llm_output
from src.services.infra.message_store import MessageStore, StoredMessage

if TYPE_CHECKING:
    from src.services.infra.session_store import SessionStore

logger = logging.getLogger(__name__)


@dataclass
class ConversationHandler:
    """Centralized handler for all conversation platforms.

    Provides unified message processing with:
    - Proper error handling and graceful fallbacks
    - Message persistence to MessageStore
    - Session state management
    - Consistent tagging for escalations
    """

    session_store: "SessionStore"
    message_store: MessageStore
    runner: GraphRunner
    fallback_message: str = field(default="")
    max_retries: int = field(default=2)
    retry_delay: float = field(default=1.0)
    _bg_tasks: set[asyncio.Task] = field(default_factory=set)

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
        """Process a user message through the full conversation pipeline."""
        state: ConversationState | None = None
        import time as _time

        _proc_start = _time.time()

        try:
            # SECURITY: Sanitize input
            from src.core.input_sanitizer import process_user_message
            text, was_sanitized = process_user_message(text)
            if was_sanitized:
                logger.warning("[SECURITY] Message sanitized for session %s", session_id)

            # Load or create session state
            _get_start = _time.time()
            try:
                state = await asyncio.wait_for(
                    asyncio.to_thread(self.session_store.get, session_id),
                    timeout=2.5,
                )
                logger.info(
                    "[SESSION %s] ⏱️ session_store.get took %.2fs",
                    session_id,
                    _time.time() - _get_start,
                )
            except TimeoutError:
                logger.warning(
                    "[SESSION %s] session_store.get timed out (>2.5s); continuing with empty state",
                    session_id,
                )
                state = None

            # Ensure state has required structure
            if not state or not isinstance(state, dict):
                state = ConversationState(
                    messages=[],
                    metadata={
                        "session_id": session_id,
                        "vision_greeted": False,
                        "has_image": False,
                    },
                    current_state="STATE_0_INIT",
                    dialog_phase="INIT",
                    should_escalate=False,
                    has_image=False,
                    detected_intent=None,
                    selected_products=[],
                    offered_products=[],
                    step_number=0,
                )
            if "messages" not in state:
                state["messages"] = []
            if "metadata" not in state:
                state["metadata"] = {"session_id": session_id, "vision_greeted": False}
            state["metadata"].setdefault("session_id", session_id)
            state["metadata"].setdefault("thread_id", state["metadata"].get("thread_id", session_id))

            state.setdefault("session_id", session_id)
            state["messages"].append({"role": "user", "content": text})

            # Reset image flags
            state["has_image"] = False
            state["image_url"] = None
            state["metadata"]["has_image"] = False
            state["metadata"]["image_url"] = None

            if extra_metadata:
                state["metadata"].update(extra_metadata)
                if extra_metadata.get("has_image"):
                    from src.services.infra.media_utils import normalize_image_url
                    normalized = normalize_image_url(extra_metadata.get("image_url"))
                    if normalized:
                        state["has_image"] = True
                        state["image_url"] = normalized
                        state["metadata"]["image_url"] = normalized

            # Trace ID
            trace_id = None
            if extra_metadata and isinstance(extra_metadata, dict):
                trace_id = str(extra_metadata.get("trace_id") or "").strip() or None
            if not trace_id:
                trace_id = str(uuid.uuid4())
            state["trace_id"] = trace_id

            # DEBUG log
            if settings.DEBUG_TRACE_LOGS:
                debug_log.request_start(
                    session_id=session_id,
                    user_message=text,
                    has_image=state.get("has_image", False),
                    metadata=state.get("metadata"),
                )

            # Persist user message
            self._persist_user_message(session_id, text)

            # Invoke agent
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

            result_state = apply_transition_guardrails(
                session_id=session_id,
                before_state=before_invoke_state,
                after_state=result_state,
                user_text=text,
            )

            # Parse response
            agent_response = self._parse_response(result_state, session_id)

            # Log outgoing message
            preview_text = ""
            try:
                preview_text = "\n".join([
                    m.content for m in (agent_response.messages or [])
                    if getattr(m, "content", None)
                ])
            except Exception:
                preview_text = ""
            logger.info(
                "📤 Outgoing message (state=%s, intent=%s): %s",
                agent_response.metadata.current_state,
                agent_response.metadata.intent,
                preview_text[:200] + "..." if len(preview_text) > 200 else preview_text,
            )

            # Persist assistant response
            self._persist_assistant_message(session_id, agent_response)

            # Save updated state
            await asyncio.to_thread(self.session_store.save, session_id, result_state)

            # Escalation notification
            try:
                is_escalation = bool(
                    agent_response.escalation
                    or (agent_response.metadata.escalation_level not in (None, "", "NONE"))
                    or bool(result_state.get("should_escalate"))
                )
                if is_escalation:
                    from src.services.infra.notification_service import NotificationService
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
                    try:
                        details["products"] = [p.model_dump() for p in (agent_response.products or [])]
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

            # DEBUG log
            if settings.DEBUG_TRACE_LOGS:
                debug_log.request_end(
                    session_id=session_id,
                    response_preview=agent_response if isinstance(agent_response, str) else str(agent_response)[:100],
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
            error_type = type(e).__name__
            error_msg = str(e)
            logger.exception(
                "Unexpected error processing message for session %s: %s: %s",
                session_id,
                error_type,
                error_msg[:500],  # Limit error message length
            )
            return self._build_fallback_result(session_id, state, f"{error_type}: {error_msg}")

    async def _invoke_agent(self, state: ConversationState) -> ConversationState:
        """Invoke the LangGraph agent with retry logic."""
        metadata = state.get("metadata", {})
        session_id = metadata.get("session_id", "unknown")
        thread_id = metadata.get("thread_id", session_id)
        last_error: Exception | None = None

        # Validate runner is not None
        if self.runner is None:
            error_msg = f"Runner is None for session {session_id}. Graph was not initialized properly."
            logger.error(
                "%s Runner type: None, Runner value: %s",
                error_msg,
                self.runner,
            )
            raise AgentInvocationError(error_msg, session_id=session_id) from ValueError("runner is None")

        # Log runner type for diagnostics (use INFO level so it always appears)
        logger.info(
            "[SESSION %s] Runner validation: type=%s, has_ainvoke=%s, ainvoke_type=%s",
            session_id,
            type(self.runner).__name__,
            hasattr(self.runner, "ainvoke"),
            type(getattr(self.runner, "ainvoke", None)).__name__ if hasattr(self.runner, "ainvoke") else "N/A",
        )

        # Validate runner has ainvoke method
        if not hasattr(self.runner, "ainvoke"):
            error_msg = f"Runner for session {session_id} does not have ainvoke method. Type: {type(self.runner).__name__}"
            logger.error(
                "%s Runner attributes: %s",
                error_msg,
                dir(self.runner) if self.runner else "N/A",
            )
            raise AgentInvocationError(error_msg, session_id=session_id) from AttributeError("runner.ainvoke not found")

        # Validate ainvoke is not None (can happen if attribute exists but is None)
        ainvoke_method = getattr(self.runner, "ainvoke", None)
        if ainvoke_method is None:
            error_msg = f"Runner.ainvoke is None for session {session_id}. Type: {type(self.runner).__name__}"
            logger.error(
                "%s Runner type: %s, Runner repr: %s",
                error_msg,
                type(self.runner).__name__,
                repr(self.runner)[:200],
            )
            raise AgentInvocationError(error_msg, session_id=session_id) from ValueError("runner.ainvoke is None")

        config = {"configurable": {"thread_id": thread_id}}

        for attempt in range(self.max_retries + 1):
            try:
                # Additional check: ensure ainvoke is callable
                if not callable(ainvoke_method):
                    error_msg = f"Runner.ainvoke is not callable for session {session_id}. Type: {type(ainvoke_method).__name__}"
                    logger.error(error_msg)
                    raise AgentInvocationError(error_msg, session_id=session_id) from TypeError("runner.ainvoke is not callable")
                
                result = await ainvoke_method(state, config=config)
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
        """Parse the agent response from the result state."""
        agent_response_data = result_state.get("agent_response")
        current_state = result_state.get("current_state", "STATE_0_INIT")

        if agent_response_data:
            try:
                return self._convert_support_to_agent_response(agent_response_data, session_id)
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

    def _convert_support_to_agent_response(
        self, data: dict[str, Any], session_id: str
    ) -> AgentResponse:
        """Convert SupportResponse to AgentResponse."""
        raw_messages = data.get("messages", [])
        messages = [
            Message(
                type=m.get("type", "text"),
                content=m.get("content") or m.get("text") or "",
            )
            for m in raw_messages
        ]
        if not messages:
            messages = [Message(type="text", content="")]

        raw_meta = data.get("metadata", {})
        metadata = Metadata(
            session_id=raw_meta.get("session_id", session_id),
            current_state=raw_meta.get("current_state", "STATE_0_INIT"),
            intent=raw_meta.get("intent", "UNKNOWN_OR_EMPTY"),
            escalation_level=raw_meta.get("escalation_level", "NONE"),
        )

        escalation = None
        raw_esc = data.get("escalation")
        if raw_esc:
            escalation = Escalation(
                level=raw_esc.get("level", raw_meta.get("escalation_level", "L1")),
                reason=raw_esc.get("reason", "Escalation requested"),
                target=raw_esc.get("target", "human_operator"),
            )

        products = []
        for idx, p in enumerate(data.get("products", [])):
            try:
                product_id = p.get("id") or p.get("product_id") or (idx + 1)
                price = p.get("price") or 0
                photo_url = p.get("photo_url") or p.get("image_url") or ""

                if not product_id or int(product_id) <= 0:
                    product_id = idx + 1
                if price == 0:
                    price = 1

                products.append(
                    Product(
                        id=int(product_id),
                        name=p.get("name", ""),
                        size=p.get("size", "") or "",
                        color=p.get("color", "") or "",
                        price=float(price),
                        photo_url=photo_url,
                    )
                )
            except Exception as exc:
                logger.debug("Skipping product in response conversion: %s", exc)

        return AgentResponse(
            event=data.get("event", "simple_answer"),
            messages=messages,
            products=products,
            metadata=metadata,
            escalation=escalation,
        )

    def _persist_user_message(self, session_id: str, text: str) -> None:
        """Store the user message in the message store."""
        msg = StoredMessage(session_id=session_id, role="user", content=text)
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

    def _persist_assistant_message(self, session_id: str, response: AgentResponse) -> None:
        """Store the assistant response with appropriate tags."""
        tags = [MessageTag.HUMAN_NEEDED] if response.escalation else []
        msg = StoredMessage(
            session_id=session_id,
            role="assistant",
            content=response.model_dump_json(),
            tags=tags,
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
        # Ensure fallback text is not empty
        if not fallback_text or not fallback_text.strip():
            from src.core.human_responses import get_human_response
            fallback_text = get_human_response("error")
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

        self._persist_assistant_message(session_id, fallback_response)

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
    session_store: "SessionStore",
    message_store: MessageStore,
    runner: GraphRunner,
    fallback_message: str | None = None,
) -> ConversationHandler:
    """Factory function to create a ConversationHandler with dependencies."""
    # Validate runner is not None
    if runner is None:
        logger.error(
            "create_conversation_handler called with None runner. "
            "This indicates the graph was not initialized properly."
        )
        raise ValueError(
            "runner cannot be None. Use get_active_graph() to get a valid runner, "
            "or ensure the graph is properly initialized before creating the handler."
        )

    # Log runner type for diagnostics
    logger.debug(
        "Creating ConversationHandler with runner type: %s, has ainvoke: %s",
        type(runner).__name__,
        hasattr(runner, "ainvoke"),
    )

    # Validate runner has ainvoke method (check protocol compliance)
    if not hasattr(runner, "ainvoke"):
        logger.error(
            "create_conversation_handler called with invalid runner. "
            "Type: %s, Attributes: %s",
            type(runner).__name__,
            [attr for attr in dir(runner) if not attr.startswith("_")][:10],
        )
        raise ValueError(
            f"runner must implement GraphRunner protocol (have ainvoke method). "
            f"Got type: {type(runner).__name__}"
        )

    kwargs: dict[str, Any] = {
        "session_store": session_store,
        "message_store": message_store,
        "runner": runner,
    }
    if fallback_message:
        kwargs["fallback_message"] = fallback_message

    return ConversationHandler(**kwargs)

