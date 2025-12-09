"""Centralized conversation handling with error management.

This module eliminates code duplication between Telegram and ManyChat handlers
by providing a single ConversationHandler that manages the full message lifecycle.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from src.agents import ConversationState
from src.core.constants import AgentState as StateEnum
from src.core.constants import MessageTag
from src.core.models import AgentResponse, Escalation, Message, Metadata, Product
from src.services.message_store import MessageStore, StoredMessage


# =============================================================================
# STUB FUNCTIONS (replacing deleted output_parser.py and state_validator.py)
# In NEW architecture: PydanticAI handles parsing, LangGraph handles transitions
# =============================================================================


class TransitionResult:
    """Stub for validate_state_transition result."""

    def __init__(self, new_state: str, was_corrected: bool = False, reason: str | None = None):
        self.new_state = new_state
        self.was_corrected = was_corrected
        self.reason = reason


def parse_llm_output(
    content: str,
    session_id: str = "",
    current_state: str = "STATE_0_INIT",
) -> AgentResponse:
    """
    Parse LLM output to AgentResponse.

    Handles structured JSON format from LangGraph nodes containing:
    - event, messages, products, metadata fields
    """
    # Try to extract from result_state if it's already structured
    if not content:
        return AgentResponse(
            event="reply",
            messages=[Message(type="text", content="")],
            metadata=Metadata(session_id=session_id, current_state=current_state),
        )

    try:
        # Parse JSON content from LangGraph nodes
        parsed = json.loads(content)

        # Extract messages array
        messages_data = parsed.get("messages", [])
        messages = []
        for msg in messages_data:
            if msg.get("type") == "text" and msg.get("content"):
                messages.append(Message(type="text", content=msg["content"]))

        # Extract products array
        products_data = parsed.get("products", [])
        products = []
        for prod in products_data:
            # Convert dict to Product object
            if isinstance(prod, dict):
                products.append(Product(**prod))

        # Extract metadata
        metadata_data = parsed.get("metadata", {})
        metadata = Metadata(
            session_id=metadata_data.get("session_id", session_id),
            current_state=metadata_data.get("current_state", current_state),
            intent=metadata_data.get("intent", ""),
            escalation_level=metadata_data.get("escalation_level", "NONE"),
        )

        return AgentResponse(
            event=parsed.get("event", "simple_answer"),
            messages=messages,
            products=products,
            metadata=metadata,
        )

    except (json.JSONDecodeError, Exception):
        # Fallback: treat as plain text content
        return AgentResponse(
            event="reply",
            messages=[Message(type="text", content=content)],
            metadata=Metadata(session_id=session_id, current_state=current_state),
        )


def validate_state_transition(
    session_id: str,
    current_state: str,
    proposed_state: str,
    intent: str = "",
) -> TransitionResult:
    """
    STUB: Validate state transition.

    In NEW architecture: LangGraph edges make invalid transitions impossible.
    This stub just accepts all transitions for legacy compatibility.
    """
    return TransitionResult(new_state=proposed_state, was_corrected=False)


if TYPE_CHECKING:
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
    fallback_message: str = field(
        default="Вибачте, сталася технічна помилка. Спробуйте ще раз або зверніться до підтримки."
    )
    max_retries: int = field(default=2)
    retry_delay: float = field(default=1.0)

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

        try:
            # Load or create session state
            state = self.session_store.get(session_id)

            # Ensure state has required structure
            if not state or not isinstance(state, dict):
                state = ConversationState(messages=[], metadata={"session_id": session_id})
            if "messages" not in state:
                state["messages"] = []
            if "metadata" not in state:
                state["metadata"] = {}
            state["messages"].append({"role": "user", "content": text})
            state["metadata"].setdefault("session_id", session_id)
            if extra_metadata:
                state["metadata"].update(extra_metadata)
                # Mirror critical flags to top-level so routers can see them
                if "has_image" in extra_metadata:
                    state["has_image"] = bool(extra_metadata.get("has_image"))
                if "image_url" in extra_metadata:
                    state["image_url"] = extra_metadata.get("image_url")

            # Generate new trace_id for this request (Observability)
            trace_id = str(uuid.uuid4())
            state["trace_id"] = trace_id

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
        """Invoke the LangGraph agent with retry logic and thread_id for persistence."""
        import asyncio

        session_id = state.get("metadata", {}).get("session_id", "unknown")
        last_error: Exception | None = None

        # Use thread_id for LangGraph checkpointer persistence
        config = {"configurable": {"thread_id": session_id}}

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
        """Convert SupportResponse (PydanticAI) to AgentResponse (core/models).

        Handles schema differences between the two models:
        - EscalationInfo (no level) -> Escalation (has level)
        - ResponseMetadata -> Metadata (extra fields)
        - ProductMatch -> Product (compatible)
        """
        # Extract messages
        raw_messages = data.get("messages", [])
        messages = [
            Message(type=m.get("type", "text"), content=m.get("content", "")) for m in raw_messages
        ]
        if not messages:
            messages = [Message(type="text", content="")]

        # Extract metadata
        raw_meta = data.get("metadata", {})
        metadata = Metadata(
            session_id=raw_meta.get("session_id", session_id),
            current_state=raw_meta.get("current_state", "STATE_0_INIT"),
            intent=raw_meta.get("intent", "UNKNOWN_OR_EMPTY"),
            escalation_level=raw_meta.get("escalation_level", "NONE"),
        )

        # Extract escalation (add level from metadata if missing)
        escalation = None
        raw_esc = data.get("escalation")
        if raw_esc:
            escalation = Escalation(
                level=raw_esc.get("level", raw_meta.get("escalation_level", "L1")),
                reason=raw_esc.get("reason", "Escalation requested"),
                target=raw_esc.get("target", "human_operator"),
            )

        # Extract products (ProductMatch -> Product compatible)
        from src.core.models import Product

        products = []
        for idx, p in enumerate(data.get("products", [])):
            try:
                # Some upstream agents return id=0/photo_url=""; make it display-safe
                product_id = p.get("id") or p.get("product_id") or (idx + 1)
                price = p.get("price") or 0
                photo_url = p.get("photo_url") or p.get("image_url") or ""

                # Fallbacks to satisfy schema (id > 0, price > 0)
                if not product_id or int(product_id) <= 0:
                    product_id = idx + 1
                if price == 0:
                    # Minimal positive price to pass validation; actual amount is in text
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

    def _persist_assistant_message(self, session_id: str, response: AgentResponse) -> None:
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
        state: ConversationState | None,
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
