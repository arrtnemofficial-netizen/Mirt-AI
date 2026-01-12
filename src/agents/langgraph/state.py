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


class ConversationState(BaseConversationState, total=False):
    """
    Production conversation state.

    Every field has a proper reducer for LangGraph's state management.
    """

    # Core conversation data (Overrides with Annotated reducers)
    messages: Annotated[list[dict[str, Any]], add_messages_capped]
    current_state: str  # FSM state (STATE_0_INIT, etc.)
    metadata: Annotated[dict[str, Any], merge_dict]

    # Other fields are inherited from BaseConversationState!
    # Only re-declare if adding Annotated reducers.

    # agent_response needs reducer?
    agent_response: Annotated[dict[str, Any], replace_value]
     
    # step_number needs reducer?
    step_number: Annotated[int, replace_value]
    
    # We can omit re-declaring non-Annotated fields as they come from BaseConversationState





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
    # CRITICAL: Ensure vision flags are reset for fresh start
    # This is especially important for /restart command
    base_metadata = {
        "session_id": session_id,
        "channel": "unknown",
        "language": "uk",
        "vision_greeted": False,  # CRITICAL: Reset vision greeting flag
        "has_image": False,  # CRITICAL: Reset image flag
        "image_url": None,  # CRITICAL: Clear image URL
        **(metadata or {}),
    }
    # Override metadata to ensure vision flags are reset even if passed in
    base_metadata["vision_greeted"] = False
    base_metadata["has_image"] = False
    base_metadata["image_url"] = None

    base_state: ConversationState = {
        # Core
        "messages": messages or [],
        "current_state": State.STATE_0_INIT.value,
        "metadata": base_metadata,
        # Dialog Phase (Turn-Based State Machine)
        "dialog_phase": "INIT",
        # Session
        "session_id": session_id,
        "trace_id": kwargs.get("trace_id"),  # Should be generated at entry point
        "thread_id": session_id,  # Use same ID for LangGraph threading
        # Intent
        "detected_intent": None,
        "has_image": False,  # CRITICAL: Reset at top level too
        "image_url": None,  # CRITICAL: Clear at top level too
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
        # Time travel support (prefixed to avoid LangGraph reserved names)
        "saved_checkpoint_id": None,
        "saved_parent_checkpoint_id": None,
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
# VALID DIALOG PHASES (Single Source of Truth)
# =============================================================================

VALID_DIALOG_PHASES: frozenset[str] = frozenset({
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
    "COMPLETED",
    "COMPLAINT",
    "OUT_OF_DOMAIN",
    "ESCALATED",  # Used by vision/escalation nodes
    # "CRM_ERROR_HANDLING",  # Removed - CRM orders integration disabled
})

# Map: FSM state -> allowed dialog_phases
# This ensures current_state and dialog_phase are consistent
STATE_TO_ALLOWED_PHASES: dict[State, frozenset[str]] = {
    State.STATE_0_INIT: frozenset({"INIT", "DISCOVERY", "VISION_DONE", "WAITING_FOR_SIZE", "WAITING_FOR_DELIVERY_DATA", "COMPLAINT", "COMPLETED", "OUT_OF_DOMAIN"}),
    State.STATE_1_DISCOVERY: frozenset({"DISCOVERY", "WAITING_FOR_SIZE", "SIZE_COLOR_DONE", "WAITING_FOR_DELIVERY_DATA", "COMPLAINT", "COMPLETED", "OUT_OF_DOMAIN"}),
    State.STATE_2_VISION: frozenset({"VISION_DONE", "DISCOVERY", "WAITING_FOR_SIZE", "OUT_OF_DOMAIN"}),
    State.STATE_3_SIZE_COLOR: frozenset({"WAITING_FOR_SIZE", "WAITING_FOR_COLOR", "SIZE_COLOR_DONE"}),
    State.STATE_4_OFFER: frozenset({"OFFER_MADE", "WAITING_FOR_DELIVERY_DATA"}),
    State.STATE_5_PAYMENT_DELIVERY: frozenset({"WAITING_FOR_DELIVERY_DATA", "WAITING_FOR_PAYMENT_METHOD", "WAITING_FOR_PAYMENT_PROOF", "UPSELL_OFFERED"}),
    State.STATE_6_UPSELL: frozenset({"UPSELL_OFFERED", "COMPLETED"}),
    State.STATE_7_END: frozenset({"COMPLETED"}),
    State.STATE_8_COMPLAINT: frozenset({"COMPLAINT", "COMPLETED", "ESCALATED"}),
    State.STATE_9_OOD: frozenset({"OUT_OF_DOMAIN", "COMPLETED"}),
}


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
