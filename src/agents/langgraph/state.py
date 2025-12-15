"""
Conversation State Definition.
==============================
Single source of truth for graph state.
Uses TypedDict with Annotated reducers for proper LangGraph integration.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from src.core.state_machine import State


# =============================================================================
# REDUCERS (how state fields are updated)
# =============================================================================


def replace_value(current: Any, new: Any) -> Any:
    """Simple replacement reducer - new value wins."""
    return new


def merge_dict(current: dict, new: dict) -> dict:
    """Merge dictionaries - new keys override old."""
    if current is None:
        return new or {}
    if new is None:
        return current
    return {**current, **new}


def append_list(current: list, new: list) -> list:
    """Append to list without duplicates."""
    if current is None:
        return new or []
    if new is None:
        return current
    return current + [x for x in new if x not in current]


# =============================================================================
# CONVERSATION STATE
# =============================================================================


class ConversationState(TypedDict, total=False):
    """
    Production conversation state.

    Every field has a proper reducer for LangGraph's state management.
    """

    # Core conversation data
    messages: Annotated[list[dict[str, Any]], add_messages]
    current_state: str  # FSM state (STATE_0_INIT, etc.)
    metadata: Annotated[dict[str, Any], merge_dict]

    # ==========================================================================
    # DIALOG PHASE (Turn-Based State Machine)
    # ==========================================================================
    # This is the KEY field for turn-based conversation!
    # Master router checks this to know where to continue the dialog.
    #
    # ПОВНИЙ СПИСОК ФАЗ (відповідає n8n state machine):
    #
    #   INIT                      - STATE_0: Новий діалог, потрібен intent detection
    #   DISCOVERY                 - STATE_1: Збір контексту (зріст, тип речі, подія)
    #   VISION_DONE               - STATE_2: Vision впізнав товар, чекаємо уточнення
    #   WAITING_FOR_SIZE          - STATE_3: Потрібен розмір (зріст дитини)
    #   WAITING_FOR_COLOR         - STATE_3: Потрібен вибір кольору
    #   SIZE_COLOR_DONE           - STATE_3→4: Є розмір і колір, готові до offer
    #   OFFER_MADE                - STATE_4: Пропозиція зроблена, чекаємо "Беру"
    #   WAITING_FOR_DELIVERY_DATA - STATE_5: Чекаємо ПІБ, телефон, НП
    #   WAITING_FOR_PAYMENT_METHOD- STATE_5: Чекаємо вибір способу оплати
    #   WAITING_FOR_PAYMENT_PROOF - STATE_5: Чекаємо скрін оплати
    #   UPSELL_OFFERED            - STATE_6: Запропонували допродаж
    #   COMPLETED                 - STATE_7: Діалог завершено
    #   COMPLAINT                 - STATE_8: Скарга, ескалація
    #   OUT_OF_DOMAIN             - STATE_9: Поза доменом
    # ==========================================================================
    dialog_phase: str

    # Session identification
    session_id: str
    trace_id: str  # UUID for the current interaction chain
    thread_id: str  # LangGraph thread for persistence

    # Intent & routing
    detected_intent: str | None
    has_image: bool
    image_url: str | None

    # Products & offers
    selected_products: list[dict[str, Any]]
    offered_products: list[dict[str, Any]]

    # Moderation
    moderation_result: dict[str, Any] | None
    should_escalate: bool
    escalation_reason: str | None

    # Tool execution
    tool_plan_result: dict[str, Any] | None
    tool_errors: list[str]

    # Latest structured agent response (PydanticAI output)
    agent_response: Annotated[dict[str, Any], replace_value]

    # Validation & self-correction
    validation_errors: list[str]
    retry_count: int
    max_retries: int
    last_error: str | None

    # Payment flow (human-in-the-loop)
    awaiting_human_approval: bool
    approval_type: Literal["payment", "refund", "discount", None]
    approval_data: dict[str, Any] | None
    human_approved: bool | None

    # Time travel support (prefixed to avoid LangGraph reserved names)
    saved_checkpoint_id: str | None
    saved_parent_checkpoint_id: str | None
    step_number: int

    # ==========================================================================
    # MEMORY SYSTEM (Titans-like)
    # ==========================================================================
    # Populated by memory_context_node, consumed by AgentDeps
    memory_profile: Any  # UserProfile from memory_models
    memory_facts: list[Any]  # list[Fact] from memory_models
    memory_context_prompt: str | None  # Pre-formatted prompt block


# =============================================================================
# STATE FACTORY
# =============================================================================


def create_initial_state(
    session_id: str,
    messages: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> ConversationState:
    """
    Create a properly initialized state.

    Args:
        session_id: Unique session identifier (becomes thread_id too)
        messages: Initial message history
        metadata: Additional metadata (channel, language, etc.)
        **kwargs: Override any state field

    Returns:
        Fully initialized ConversationState
    """
    base_state: ConversationState = {
        # Core
        "messages": messages or [],
        "current_state": State.STATE_0_INIT.value,
        "metadata": {
            "session_id": session_id,
            "channel": "unknown",
            "language": "uk",
            **(metadata or {}),
        },
        # Dialog Phase (Turn-Based State Machine)
        "dialog_phase": "INIT",
        # Session
        "session_id": session_id,
        "trace_id": kwargs.get("trace_id"),  # Should be generated at entry point
        "thread_id": session_id,  # Use same ID for LangGraph threading
        # Intent
        "detected_intent": None,
        "has_image": False,
        "image_url": None,
        # Products
        "selected_products": [],
        "offered_products": [],
        # Moderation
        "moderation_result": None,
        "should_escalate": False,
        "escalation_reason": None,
        # Tools
        "tool_plan_result": None,
        "tool_errors": [],
        # Validation (self-correction)
        "validation_errors": [],
        "retry_count": 0,
        "max_retries": 3,
        "last_error": None,
        # Payment (human-in-the-loop)
        "awaiting_human_approval": False,
        "approval_type": None,
        "approval_data": None,
        "human_approved": None,
        # Time travel
        "checkpoint_id": None,
        "parent_checkpoint_id": None,
        "step_number": 0,
        # Memory System (Titans-like)
        "memory_profile": None,
        "memory_facts": [],
        "memory_context_prompt": None,
    }

    # Apply overrides
    for key, value in kwargs.items():
        if key in base_state:
            base_state[key] = value

    return base_state


def get_state_snapshot(state: ConversationState) -> dict[str, Any]:
    """
    Get a JSON-serializable snapshot of the state.
    Useful for debugging and logging.
    """
    return {
        "session_id": state.get("session_id"),
        "current_state": state.get("current_state"),
        "dialog_phase": state.get("dialog_phase"),  # Turn-Based State Machine
        "detected_intent": state.get("detected_intent"),
        "has_image": state.get("has_image"),
        "products_count": len(state.get("selected_products", [])),
        "retry_count": state.get("retry_count", 0),
        "awaiting_approval": state.get("awaiting_human_approval", False),
        "step_number": state.get("step_number", 0),
        "validation_errors": state.get("validation_errors", []),
    }


# =============================================================================
# STATE VALIDATORS
# =============================================================================


def validate_state(state: ConversationState) -> list[str]:
    """
    Validate state consistency.
    Returns list of errors (empty = valid).
    """
    errors = []

    if not state.get("session_id"):
        errors.append("Missing session_id")

    if not state.get("trace_id"):
        # Not a blocking error yet, but worth noting
        pass

    if not state.get("current_state"):
        errors.append("Missing current_state")

    # Check FSM state is valid
    current = state.get("current_state", "")
    try:
        State(current)
    except ValueError:
        errors.append(f"Invalid FSM state: {current}")

    # Check retry count
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    if retry_count > max_retries:
        errors.append(f"Retry count ({retry_count}) exceeds max ({max_retries})")

    return errors
