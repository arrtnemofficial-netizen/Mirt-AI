"""
Conversation state definition.
Single source of truth for graph state and reducers.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from langgraph.graph.message import add_messages  # noqa: TCH002 - required at runtime
from typing_extensions import TypedDict

from src.conf.config import settings
from src.core.state_machine import State

logger = logging.getLogger(__name__)


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


def _resolve_state_max_messages() -> int:
    try:
        return int(getattr(settings, "STATE_MAX_MESSAGES", 100))
    except Exception:
        return 100


def add_messages_capped(current: list, new: list) -> list:
    """Append messages but keep only the last N to prevent unbounded growth."""
    merged = add_messages(current, new)
    max_messages = _resolve_state_max_messages()
    if max_messages > 0 and len(merged) > max_messages:
        trimmed_count = len(merged) - max_messages
        try:
            from src.services.core.observability import track_metric

            track_metric("state_messages_trimmed", trimmed_count)
        except Exception:
            pass
        logger.info(
            "[STATE] Trimmed messages: trimmed=%d kept=%d",
            trimmed_count,
            max_messages,
        )
        return merged[-max_messages:]
    return merged


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
    dialog_phase: str | None

    # Memory system (SSOT for Titans context)
    memory_profile: dict[str, Any] | None
    memory_facts: list[str]
    memory_context_prompt: str | None

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
        "dialog_phase": "INIT",

        # Memory
        "memory_profile": None,
        "memory_facts": [],
        "memory_context_prompt": None,

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


def validate_state_structure(state: Any) -> tuple[bool, list[str]]:
    """
    Validate state structure (types and required fields).
    
    This function checks the structural integrity of a conversation state
    without modifying it. Used for defensive validation when loading state
    from database or external sources.
    
    Args:
        state: State object to validate (can be dict, ConversationState, or None)
    
    Returns:
        Tuple of (is_valid: bool, errors: list[str])
        - is_valid: True if structure is valid, False otherwise
        - errors: List of validation error messages (empty if valid)
    
    Note:
        This function does NOT modify the state. It only validates structure.
        For logical consistency checks, use validate_state() instead.
    """
    errors: list[str] = []
    
    # Check if state is a dict-like object
    if state is None:
        return False, ["State is None"]
    
    if not isinstance(state, dict):
        return False, [f"State must be a dict, got {type(state).__name__}"]
    
    # Required fields check
    required_fields = {
        "session_id": str,
        "messages": list,
        "metadata": dict,
        "current_state": str,
    }
    
    for field_name, expected_type in required_fields.items():
        if field_name not in state:
            errors.append(f"Missing required field: {field_name}")
            continue
        
        field_value = state[field_name]
        
        # Check type (allow None for optional fields, but log if unexpected)
        if field_value is None:
            if field_name in ("session_id", "current_state"):
                errors.append(f"Required field {field_name} cannot be None")
            continue
        
        if not isinstance(field_value, expected_type):
            actual_type = type(field_value).__name__
            errors.append(
                f"Field {field_name} has wrong type: expected {expected_type.__name__}, got {actual_type}"
            )
    
    # Additional type checks for optional but important fields
    optional_typed_fields = {
        "selected_products": list,
        "offered_products": list,
        "validation_errors": list,
        "tool_errors": list,
        "memory_facts": list,
        "should_escalate": bool,
        "has_image": bool,
        "retry_count": int,
        "max_retries": int,
        "step_number": int,
    }
    
    for field_name, expected_type in optional_typed_fields.items():
        if field_name in state:
            field_value = state[field_name]
            if field_value is not None and not isinstance(field_value, expected_type):
                actual_type = type(field_value).__name__
                errors.append(
                    f"Field {field_name} has wrong type: expected {expected_type.__name__} or None, got {actual_type}"
                )
    
    # Validate messages structure (should be list of dicts)
    if "messages" in state and isinstance(state["messages"], list):
        for idx, msg in enumerate(state["messages"]):
            if not isinstance(msg, dict):
                errors.append(f"Message at index {idx} is not a dict, got {type(msg).__name__}")
            elif "role" not in msg and "content" not in msg:
                # Allow other formats but warn if completely invalid
                if not any(key in msg for key in ("role", "type", "content", "text")):
                    errors.append(f"Message at index {idx} has no recognizable message fields")
    
    # Validate metadata structure
    if "metadata" in state and isinstance(state["metadata"], dict):
        # Metadata should be a dict, but we don't enforce specific keys
        # (it's flexible for different use cases)
        pass
    
    is_valid = len(errors) == 0
    return is_valid, errors


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


__all__ = [
    "ConversationState",
    "create_initial_state",
    "get_state_snapshot",
    "validate_state",
    "validate_state_structure",
    "replace_value",
    "merge_dict",
    "append_list",
    "add_messages_capped",
]
