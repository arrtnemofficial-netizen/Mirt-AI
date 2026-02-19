"""
Conversation State Definition.
==============================
Single source of truth for graph state.
Uses TypedDict with Annotated reducers for proper LangGraph integration.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from src.core.models import BaseConversationState
from src.core.state_machine import (
    State,
    STATE_TO_ALLOWED_PHASES,
    VALID_DIALOG_PHASES,
    get_default_dialog_phase_for_state,
)
from src.core.state_schema import StateSchema

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


def add_messages_capped(current: list, new: list) -> list:
    """Append messages but keep only the last N to prevent unbounded growth."""
    merged = add_messages(current, new)
    try:
        max_messages = int(os.getenv("STATE_MAX_MESSAGES", "100") or "100")
    except Exception:
        max_messages = 100
    if max_messages > 0 and len(merged) > max_messages:
        return merged[-max_messages:]
    return merged


# =============================================================================
# CONVERSATION STATE
# =============================================================================


class ConversationState(StateSchema):
    """
    Production conversation state (Pydantic V2).
    
    Inherits fields from StateSchema (SSOT).
    Adds LangGraph Reducers via Annotated.
    """
    
    # Redefine fields to attach Reducers
    messages: Annotated[list[Any], add_messages_capped]
    
    # Metadata merging is crucial
    metadata: Annotated[dict[str, Any], merge_dict]

    # For now, default Pydantic behavior (replace) is fine for strings/ints.
    # We only annotate what needs SPECIAL reduction logic (merging/appending).
    
    # Resolves InvalidUpdateError for parallel step updates
    step_number: Annotated[int, replace_value]






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
    base_metadata = {
        "session_id": session_id,
        "channel": "unknown",
        "language": "uk",
        "vision_greeted": False,
        **(metadata or {}),
    }
    base_metadata.setdefault("vision_greeted", False)

    base_state_dict = {
        # Core
        "messages": messages or [],
        "current_state": State.STATE_0_INIT.value,
        "metadata": base_metadata,
        # Dialog Phase (Turn-Based State Machine)
        "dialog_phase": "INIT",
        # Session
        "session_id": session_id,
        "trace_id": kwargs.get("trace_id", ""),  
        "thread_id": session_id,  
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
        # Time travel support
        "saved_checkpoint_id": None,
        "saved_parent_checkpoint_id": None,
        "step_number": 0,
        # Memory System
        "memory_profile": None,
        "memory_facts": [],
        "memory_context_prompt": None,
    }

    # Apply overrides
    for key, value in kwargs.items():
        base_state_dict[key] = value

    return ConversationState(**base_state_dict)


def map_canonical_image_fields(
    *,
    metadata: dict[str, Any] | None,
    has_image: Any = None,
    image_url: Any = None,
) -> tuple[dict[str, Any], bool, str | None]:
    """Map inbound image fields to canonical top-level state fields.

    Canonical source of truth lives only in `state.has_image` and `state.image_url`.
    Metadata image aliases are accepted only on ingress for backward compatibility.
    """
    normalized_metadata = dict(metadata or {})

    meta_has_image = normalized_metadata.pop("has_image", None)
    meta_image_url = normalized_metadata.pop("image_url", None)

    resolved_image_url = image_url if image_url is not None else meta_image_url
    if isinstance(resolved_image_url, str):
        resolved_image_url = resolved_image_url.strip() or None
    elif resolved_image_url is not None:
        resolved_image_url = None

    resolved_has_image = has_image if has_image is not None else meta_has_image
    resolved_has_image = bool(resolved_has_image)

    if resolved_image_url:
        resolved_has_image = True
    if not resolved_has_image:
        resolved_image_url = None

    return normalized_metadata, resolved_has_image, resolved_image_url


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


# STATE_TO_ALLOWED_PHASES, VALID_DIALOG_PHASES, get_default_dialog_phase_for_state
# are imported from core.state_machine (SSOT). Re-exported here for consumers of
# agents.langgraph.state (e.g. validate_state below).


# =============================================================================
# STATE VALIDATORS
# =============================================================================


def validate_state(state: ConversationState) -> list[str]:
    """
    Validate state consistency with runtime guardrails.
    
    Checks:
    - FSM state validity
    - Dialog phase validity
    - Consistency between current_state and dialog_phase
    - Retry count limits
    
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
        return errors  # Can't validate further without current_state

    # Check FSM state is valid
    current_state_str = state.get("current_state", "")
    try:
        current_state = State(current_state_str)
    except ValueError:
        errors.append(f"Invalid FSM state: {current_state_str}")
        return errors  # Can't validate phase consistency without valid state

    # Check dialog_phase is valid
    dialog_phase = state.get("dialog_phase", "")
    if dialog_phase and dialog_phase not in VALID_DIALOG_PHASES:
        errors.append(f"Invalid dialog_phase: {dialog_phase} (not in VALID_DIALOG_PHASES)")

    # Check consistency: dialog_phase must be allowed for current_state
    if dialog_phase and current_state in STATE_TO_ALLOWED_PHASES:
        allowed_phases = STATE_TO_ALLOWED_PHASES[current_state]
        if dialog_phase not in allowed_phases:
            errors.append(
                f"Inconsistent state/phase: current_state={current_state_str}, "
                f"dialog_phase={dialog_phase} (not allowed for this state). "
                f"Allowed phases: {sorted(allowed_phases)}"
            )

    # Check retry count
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    if retry_count > max_retries:
        errors.append(f"Retry count ({retry_count}) exceeds max ({max_retries})")

    return errors


def detect_state_loop(
    state: ConversationState,
    previous_phases: list[str] | None = None,
    loop_threshold: int = 3,
) -> bool:
    """
    Detect if dialog_phase is stuck in a loop.
    
    Args:
        state: Current conversation state
        previous_phases: History of recent dialog_phases (from metadata or external tracking)
        loop_threshold: Number of identical phases in a row to consider a loop
        
    Returns:
        True if loop detected, False otherwise
    """
    current_phase = state.get("dialog_phase", "")
    if not current_phase:
        return False

    # Try to get phase history from metadata
    metadata = state.get("metadata", {})
    phase_history = previous_phases or metadata.get("dialog_phase_history", [])

    # Check if current phase repeats N times
    if len(phase_history) >= loop_threshold - 1:
        recent_phases = phase_history[-(loop_threshold - 1):] + [current_phase]
        if len(set(recent_phases)) == 1:
            return True

    return False


def validate_state_transition(
    from_state: State,
    to_state: State,
    intent: str | None = None,
) -> tuple[bool, str | None]:
    """
    Validate if a state transition is legal according to TRANSITIONS table.
    
    Args:
        from_state: Current FSM state
        to_state: Proposed next FSM state
        intent: Detected intent (optional, for better validation)
        
    Returns:
        (is_valid, error_message)
    """
    from src.core.state_machine import TRANSITIONS, Intent

    # Check if transition exists in TRANSITIONS table
    for transition in TRANSITIONS:
        if transition.from_state == from_state and transition.to_state == to_state:
            # If intent provided, check if it matches
            if intent:
                try:
                    intent_enum = Intent(intent)
                    if intent_enum in transition.when_intents:
                        return True, None
                except ValueError:
                    pass
            else:
                # Transition exists, but intent check skipped
                return True, None

    # Transition not found
    return False, (
        f"Illegal transition: {from_state.value} → {to_state.value}. "
        f"Check TRANSITIONS table in state_machine.py"
    )
