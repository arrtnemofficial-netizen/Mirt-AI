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

from src.agents import ConversationState
from src.conf.config import settings
from src.core.constants import AgentState as StateEnum
from src.core.constants import MessageTag
from src.core.debug_logger import debug_log
from src.core.models import AgentResponse, Escalation, Message, Metadata, Product
from src.services.message_store import MessageStore, StoredMessage
from src.services.observability import track_metric


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
            content_value = msg.get("content") or msg.get("text")
            if msg.get("type") == "text" and content_value:
                messages.append(Message(type="text", content=content_value))

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


_ALLOWED_DIALOG_PHASES: set[str] = {
    "INIT",
    "DISCOVERY",
    "VISION_DONE",
    "WAITING_FOR_SIZE",
    "WAITING_FOR_COLOR",
    "SIZE_COLOR_DONE",
    "OFFER_MADE",
    "WAITING_FOR_DELIVERY_DATA",
    "WAITING_FOR_PAYMENT_METHOD",
    "WAITING_FOR_PAYMENT_PROOF",
    "UPSELL_OFFERED",
    "CRM_ERROR_HANDLING",
    "ESCALATED",
    "COMPLAINT",
    "OUT_OF_DOMAIN",
    "COMPLETED",
}


def _safe_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _guard_progress_fingerprint(state: ConversationState) -> str:
    meta = state.get("metadata", {}) or {}
    payload = {
        "current_state": state.get("current_state"),
        "dialog_phase": state.get("dialog_phase"),
        "detected_intent": state.get("detected_intent"),
        "selected_products": [
            (p.get("id"), p.get("name"), p.get("size"), p.get("color"))
            for p in (state.get("selected_products") or [])
            if isinstance(p, dict)
        ],
        "offered_products": [
            (p.get("id"), p.get("name"), p.get("size"), p.get("color"))
            for p in (state.get("offered_products") or [])
            if isinstance(p, dict)
        ],
        "customer": {
            "name": meta.get("customer_name"),
            "phone": meta.get("customer_phone"),
            "city": meta.get("customer_city"),
            "nova_poshta": meta.get("customer_nova_poshta"),
        },
        "payment": {
            "payment_details_sent": meta.get("payment_details_sent"),
            "awaiting_payment_confirmation": meta.get("awaiting_payment_confirmation"),
            "payment_confirmed": meta.get("payment_confirmed"),
            "payment_proof_received": meta.get("payment_proof_received"),
        },
        "crm": {
            "crm_external_id": state.get("crm_external_id"),
            "crm_retry_count": state.get("crm_retry_count"),
            "crm_status": (state.get("crm_order_result") or {}).get("status"),
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return _safe_hash(raw)


def _apply_transition_guardrails(
    *,
    session_id: str,
    before_state: ConversationState,
    after_state: ConversationState,
    user_text: str,
) -> ConversationState:
    from src.core.state_machine import State

    meta = after_state.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        after_state["metadata"] = meta

    dialog_phase = after_state.get("dialog_phase", "INIT")
    if (
        not dialog_phase
        or not isinstance(dialog_phase, str)
        or dialog_phase not in _ALLOWED_DIALOG_PHASES
    ):
        logger.error(
            "[SESSION %s] Guardrail: invalid dialog_phase=%r -> INIT",
            session_id,
            dialog_phase,
        )
        after_state["dialog_phase"] = "INIT"

    current_state = after_state.get("current_state", State.STATE_0_INIT.value)
    normalized_state = State.from_string(str(current_state)).value
    if current_state != normalized_state:
        logger.error(
            "[SESSION %s] Guardrail: invalid current_state=%r -> %s",
            session_id,
            current_state,
            normalized_state,
        )
        after_state["current_state"] = normalized_state

    guard = meta.get("_guard")
    if not isinstance(guard, dict):
        guard = {}

    before_fp = _guard_progress_fingerprint(before_state)
    after_fp = _guard_progress_fingerprint(after_state)
    prev_count = int(guard.get("count") or 0)

    stagnant_this_turn = before_fp == after_fp
    count = (prev_count + 1) if stagnant_this_turn else 0

    guard["fp"] = after_fp
    guard["count"] = count
    guard["last_user_hash"] = _safe_hash(user_text.strip().lower())
    guard["before_fp"] = before_fp
    meta["_guard"] = guard

    if count == 5:
        track_metric(
            "loop_guard_warn",
            1,
            {
                "phase": str(after_state.get("dialog_phase") or ""),
                "state": str(after_state.get("current_state") or ""),
            },
        )
        logger.warning(
            "[SESSION %s] Guardrail: potential loop (count=%d, phase=%s, state=%s)",
            session_id,
            count,
            after_state.get("dialog_phase"),
            after_state.get("current_state"),
        )

    if count == 10:
        track_metric(
            "loop_guard_soft_recovery",
            1,
            {
                "phase": str(after_state.get("dialog_phase") or ""),
                "state": str(after_state.get("current_state") or ""),
            },
        )
        logger.error(
            "[SESSION %s] Guardrail: loop detected -> soft recovery to INIT (count=%d)",
            session_id,
            count,
        )
        after_state["dialog_phase"] = "INIT"
        after_state["current_state"] = State.STATE_0_INIT.value
        after_state["detected_intent"] = None
        after_state["last_error"] = "loop_guard_soft_recovery"
        if settings.DEBUG_TRACE_LOGS:
            debug_log.error(
                session_id=session_id,
                error_type="LoopGuard",
                message=f"Soft recovery to INIT (count={count})",
            )

    if count >= 20:
        track_metric(
            "loop_guard_escalation",
            1,
            {
                "phase": str(after_state.get("dialog_phase") or ""),
                "state": str(after_state.get("current_state") or ""),
            },
        )
        logger.error(
            "[SESSION %s] Guardrail: loop detected -> escalation (count=%d)",
            session_id,
            count,
        )
        after_state["dialog_phase"] = "COMPLAINT"
        after_state["current_state"] = State.STATE_8_COMPLAINT.value
        after_state["detected_intent"] = "COMPLAINT"
        after_state["escalation_reason"] = "Loop guard: too many repeated turns"
        after_state["should_escalate"] = True
        after_state["last_error"] = "loop_guard_escalation"
        try:
            from src.core.human_responses import get_human_response

            after_state["agent_response"] = {
                "event": "escalation",
                "messages": [{"type": "text", "content": get_human_response("escalation")}],
                "metadata": {
                    "session_id": session_id,
                    "current_state": State.STATE_8_COMPLAINT.value,
                    "intent": "COMPLAINT",
                    "escalation_level": "L1",
                },
                "escalation": {
                    "reason": after_state.get("escalation_reason") or "Loop guard",
                    "target": "human_operator",
                },
            }
        except Exception:
            pass
        if settings.DEBUG_TRACE_LOGS:
            debug_log.error(
                session_id=session_id,
                error_type="LoopGuard",
                message=f"Escalation (count={count})",
            )

    agent_response = after_state.get("agent_response")
    if isinstance(agent_response, dict):
        messages = agent_response.get("messages")
        if isinstance(messages, list):
            text_messages = [
                m for m in messages if isinstance(m, dict) and (m.get("type") in (None, "text"))
            ]
            first = text_messages[0] if text_messages else None
            first_content = first.get("content") if isinstance(first, dict) else None
            if isinstance(first_content, str):
                pass

                # TODO: Review this guardrail - it overwrites LLM responses even when using snippets
                # DISABLED for now to allow snippet-based responses
                #     if "соф" not in first_content.lower() and "менеджер" not in first_content.lower():
                #         first["content"] = "Вітаю 🎀\n---\nЗ вами MIRT_UA, менеджер Софія)"

                # TODO: Review this guardrail - it removes messages even when using snippets
                # DISABLED for now to allow snippet-based responses
                # if before_step >= 1 and not user_is_greeting:
                #     lowered_first = first_content.strip().lower()
                #     if lowered_first.startswith("вітаю") or lowered_first.startswith("вітаємо") or lowered_first.startswith("доброго"):
                #         if len(messages) > 1:
                #             messages.remove(first)

    return after_state


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

            # Load or create session state
            # CRITICAL: Use to_thread() to avoid blocking event loop!
            # Supabase client is synchronous and blocks the entire async loop
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

            # Ensure state has required structure with ALL necessary flags
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
            # Ensure core identifiers are present
            state["metadata"].setdefault("session_id", session_id)
            state["metadata"].setdefault(
                "thread_id", state["metadata"].get("thread_id", session_id)
            )

            # Ensure top-level session_id is always present (some routers read it directly)
            state.setdefault("session_id", session_id)
            state["messages"].append({"role": "user", "content": text})

            # CRITICAL: Reset image flags at start of EVERY new message
            # This prevents stale image_url from previous messages affecting routing
            # See: https://github.com/... routing bug where text messages went to vision
            state["has_image"] = False
            state["image_url"] = None
            state["metadata"]["has_image"] = False
            state["metadata"]["image_url"] = None

            if extra_metadata:
                state["metadata"].update(extra_metadata)
                # Mirror critical flags to top-level so routers can see them
                if extra_metadata.get("has_image"):
                    image_url = extra_metadata.get("image_url")
                    if isinstance(image_url, str):
                        trimmed = image_url.strip()
                        if trimmed.startswith(("http://", "https://")) and len(trimmed) <= 2000:
                            state["has_image"] = True
                            state["image_url"] = trimmed
                            state["metadata"]["image_url"] = trimmed

            # Generate or reuse trace_id for this request (Observability)
            trace_id = None
            if extra_metadata and isinstance(extra_metadata, dict):
                trace_id = str(extra_metadata.get("trace_id") or "").strip() or None
            if not trace_id:
                trace_id = str(uuid.uuid4())
            state["trace_id"] = trace_id

            # DEBUG: Log request start
            if settings.DEBUG_TRACE_LOGS:
                debug_log.request_start(
                    session_id=session_id,
                    user_message=text,
                    has_image=state.get("has_image", False),
                    metadata=state.get("metadata"),
                )

            # Persist user message
            self._persist_user_message(session_id, text)

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

            result_state = _apply_transition_guardrails(
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

            # Persist assistant response
            self._persist_assistant_message(session_id, agent_response)

            # Save updated state
            # CRITICAL: Use to_thread() to avoid blocking event loop!
            await asyncio.to_thread(self.session_store.save, session_id, result_state)

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
                    from src.services.notification_service import NotificationService

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
            Message(
                type=m.get("type", "text"),
                content=m.get("content") or m.get("text") or "",
            )
            for m in raw_messages
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
