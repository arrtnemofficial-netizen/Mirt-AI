"""
Conversation State Definition.
==============================
Single source of truth for graph state.
Uses TypedDict with Annotated reducers for proper LangGraph integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from typing_extensions import TypedDict

from src.core.state_machine import State


if TYPE_CHECKING:
    from langgraph.graph.message import add_messages


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

    # Session identification
    session_id: str
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

        # Session
        "session_id": session_id,
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
