"""
Centralized State Machine for MIRT AI Agent.
============================================
Single source of truth for:
- States (enum)
- Intents (enum)
- State transitions (FSM table)
- Platform-specific aliases (Telegram/ManyChat)

This module replaces scattered state definitions across the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
import logging

import yaml

from src.core.prompt_registry import registry
from src.conf.config import settings


# =============================================================================
# STATES (Single Source of Truth)
# =============================================================================


class State(str, Enum):
    """
    Agent conversation states.
    Names match registry-managed prompts exactly.
    """

    STATE_0_INIT = "STATE_0_INIT"
    STATE_1_DISCOVERY = "STATE_1_DISCOVERY"
    STATE_2_VISION = "STATE_2_VISION"
    STATE_3_SIZE_COLOR = "STATE_3_SIZE_COLOR"
    STATE_4_OFFER = "STATE_4_OFFER"
    STATE_5_PAYMENT_DELIVERY = "STATE_5_PAYMENT_DELIVERY"
    STATE_6_UPSELL = "STATE_6_UPSELL"
    STATE_7_END = "STATE_7_END"
    STATE_8_COMPLAINT = "STATE_8_COMPLAINT"
    STATE_9_OOD = "STATE_9_OOD"

    @classmethod
    def default(cls) -> State:
        return cls.STATE_0_INIT

    @classmethod
    def from_string(cls, value: str) -> State:
        """Parse state string with fallback to INIT."""
        if not value:
            return cls.STATE_0_INIT
        # Handle legacy format without underscore after number
        normalized = (
            value.upper()
            .replace("STATE0", "STATE_0")
            .replace("STATE1", "STATE_1")
            .replace("STATE2", "STATE_2")
            .replace("STATE3", "STATE_3")
            .replace("STATE4", "STATE_4")
            .replace("STATE5", "STATE_5")
            .replace("STATE6", "STATE_6")
            .replace("STATE7", "STATE_7")
            .replace("STATE8", "STATE_8")
            .replace("STATE9", "STATE_9")
        )
        try:
            return cls(normalized)
        except ValueError:
            return cls.STATE_0_INIT

    @property
    def display_name(self) -> str:
        """Human-readable state name for logs/UI."""
        return STATE_DISPLAY_NAMES.get(self, self.value)

    @property
    def requires_escalation(self) -> bool:
        """Check if state requires human handoff."""
        return self in (State.STATE_8_COMPLAINT, State.STATE_9_OOD)


def _load_state_machine_config() -> dict[str, Any]:
    try:
        content = registry.get("system.state_machine").content
    except Exception:
        return {}
    try:
        data = yaml.safe_load(content) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


# Display names for UI/logs
_DEFAULT_STATE_DISPLAY_NAMES: dict[State, str] = {
    State.STATE_0_INIT: "Init",
    State.STATE_1_DISCOVERY: "Discovery",
    State.STATE_2_VISION: "Vision",
    State.STATE_3_SIZE_COLOR: "Size/Color",
    State.STATE_4_OFFER: "Offer",
    State.STATE_5_PAYMENT_DELIVERY: "Payment/Delivery",
    State.STATE_6_UPSELL: "Upsell",
    State.STATE_7_END: "End",
    State.STATE_8_COMPLAINT: "Complaint",
    State.STATE_9_OOD: "Out of domain",
}


def _load_state_display_names() -> dict[State, str]:
    data = _load_state_machine_config()
    labels = data.get("state_labels", {})
    if not isinstance(labels, dict):
        return _DEFAULT_STATE_DISPLAY_NAMES

    result: dict[State, str] = {}
    for state in State:
        value = labels.get(state.value)
        if isinstance(value, str) and value:
            result[state] = value

    return result or _DEFAULT_STATE_DISPLAY_NAMES


STATE_DISPLAY_NAMES = _load_state_display_names()


# =============================================================================
# DIALOG PHASE → STATE MAPPING
# =============================================================================

_PHASE_TO_STATE: dict[str, State] = {
    "DISCOVERY": State.STATE_1_DISCOVERY,
    "VISION_DONE": State.STATE_2_VISION,
    "VISION_RETRY": State.STATE_2_VISION,
    "SIZE_COLOR": State.STATE_3_SIZE_COLOR,
    "OFFER_MADE": State.STATE_4_OFFER,
    "WAITING_FOR_PAYMENT_PROOF": State.STATE_5_PAYMENT_DELIVERY,
    "PAYMENT_DELIVERY": State.STATE_5_PAYMENT_DELIVERY,
    "UPSELL_OFFERED": State.STATE_6_UPSELL,
    "COMPLETED": State.STATE_7_END,
    "ESCALATED": State.STATE_7_END,
    "CRM_ERROR_HANDLING": State.STATE_5_PAYMENT_DELIVERY,
}


def expected_state_for_phase(phase: str | None) -> State | None:
    """
    Return FSM state that should correspond to the given dialog_phase.

    Used by LangGraph guards to realign states when LLM output drifts.
    """
    if not phase:
        return None
    normalized = phase.strip().upper()
    return _PHASE_TO_STATE.get(normalized)


# =============================================================================
# INTENTS (Single Source of Truth)
# =============================================================================


class Intent(str, Enum):
    """
    User intent classification labels.
    Matches INTENT_LABELS in registry-managed prompts.
    """

    GREETING_ONLY = "GREETING_ONLY"
    DISCOVERY_OR_QUESTION = "DISCOVERY_OR_QUESTION"
    PHOTO_IDENT = "PHOTO_IDENT"
    SIZE_HELP = "SIZE_HELP"
    COLOR_HELP = "COLOR_HELP"
    PAYMENT_DELIVERY = "PAYMENT_DELIVERY"
    COMPLAINT = "COMPLAINT"
    THANKYOU_SMALLTALK = "THANKYOU_SMALLTALK"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    UNKNOWN_OR_EMPTY = "UNKNOWN_OR_EMPTY"

    @classmethod
    def from_string(cls, value: str) -> Intent:
        """Parse intent string with fallback."""
        try:
            return cls(value.upper())
        except ValueError:
            return cls.UNKNOWN_OR_EMPTY


# =============================================================================
# EVENT TYPES
# =============================================================================


class EventType(str, Enum):
    """
    Agent response event types from OUTPUT_CONTRACT.

    NOTE: This enum is kept for reference but not actively used.
    The actual event types are defined as Literal in:
    - src/agents/pydantic/models.py (EventType Literal)
    - src/core/models.py (AgentResponse.event as str)
    """

    SIMPLE_ANSWER = "simple_answer"
    CLARIFYING_QUESTION = "clarifying_question"
    MULTI_OPTION = "multi_option"
    ESCALATION = "escalation"
    END_SMALLTALK = "end_smalltalk"


# =============================================================================
# ESCALATION LEVELS
# =============================================================================


class EscalationLevel(str, Enum):
    """Escalation severity levels."""

    NONE = "NONE"
    L1 = "L1"  # Basic human handoff
    L2 = "L2"  # Supervisor required
    L3 = "L3"  # Critical / security issue


# =============================================================================
# FSM TRANSITIONS (Single Source of Truth)
# =============================================================================


@dataclass(frozen=True)
class Transition:
    """Single state transition rule."""

    from_state: State
    to_state: State
    when_intents: frozenset[Intent]
    condition: str | None = None  # Human-readable condition description


# FSM Transition Table - extracted from registry-managed prompts
TRANSITIONS: list[Transition] = [
    # From STATE_0_INIT
    Transition(
        State.STATE_0_INIT,
        State.STATE_1_DISCOVERY,
        frozenset({Intent.GREETING_ONLY, Intent.DISCOVERY_OR_QUESTION}),
    ),
    Transition(State.STATE_0_INIT, State.STATE_2_VISION, frozenset({Intent.PHOTO_IDENT})),
    Transition(
        State.STATE_0_INIT,
        State.STATE_3_SIZE_COLOR,
        frozenset({Intent.SIZE_HELP, Intent.COLOR_HELP}),
    ),
    Transition(
        State.STATE_0_INIT, State.STATE_5_PAYMENT_DELIVERY, frozenset({Intent.PAYMENT_DELIVERY})
    ),
    Transition(State.STATE_0_INIT, State.STATE_8_COMPLAINT, frozenset({Intent.COMPLAINT})),
    Transition(State.STATE_0_INIT, State.STATE_7_END, frozenset({Intent.THANKYOU_SMALLTALK})),
    Transition(State.STATE_0_INIT, State.STATE_9_OOD, frozenset({Intent.OUT_OF_DOMAIN})),
    # From STATE_1_DISCOVERY
    Transition(
        State.STATE_1_DISCOVERY,
        State.STATE_3_SIZE_COLOR,
        frozenset({Intent.SIZE_HELP, Intent.COLOR_HELP, Intent.DISCOVERY_OR_QUESTION}),
    ),
    Transition(State.STATE_1_DISCOVERY, State.STATE_2_VISION, frozenset({Intent.PHOTO_IDENT})),
    Transition(State.STATE_1_DISCOVERY, State.STATE_9_OOD, frozenset({Intent.OUT_OF_DOMAIN})),
    # From STATE_2_VISION
    Transition(
        State.STATE_2_VISION,
        State.STATE_3_SIZE_COLOR,
        frozenset({Intent.SIZE_HELP, Intent.COLOR_HELP, Intent.DISCOVERY_OR_QUESTION}),
    ),
    Transition(State.STATE_2_VISION, State.STATE_9_OOD, frozenset({Intent.OUT_OF_DOMAIN})),
    # From STATE_3_SIZE_COLOR
    Transition(
        State.STATE_3_SIZE_COLOR,
        State.STATE_4_OFFER,
        frozenset({Intent.DISCOVERY_OR_QUESTION, Intent.SIZE_HELP, Intent.COLOR_HELP}),
    ),
    Transition(State.STATE_3_SIZE_COLOR, State.STATE_9_OOD, frozenset({Intent.OUT_OF_DOMAIN})),
    # From STATE_4_OFFER
    Transition(
        State.STATE_4_OFFER,
        State.STATE_5_PAYMENT_DELIVERY,
        frozenset({Intent.PAYMENT_DELIVERY}),
    ),
    Transition(
        State.STATE_4_OFFER,
        State.STATE_7_END,
        frozenset({Intent.THANKYOU_SMALLTALK}),
    ),
    # From STATE_5_PAYMENT_DELIVERY
    Transition(
        State.STATE_5_PAYMENT_DELIVERY,
        State.STATE_6_UPSELL,
        frozenset({Intent.PAYMENT_DELIVERY}),
    ),
    Transition(
        State.STATE_5_PAYMENT_DELIVERY,
        State.STATE_7_END,
        frozenset({Intent.PAYMENT_DELIVERY, Intent.THANKYOU_SMALLTALK}),
    ),
    Transition(
        State.STATE_5_PAYMENT_DELIVERY, State.STATE_9_OOD, frozenset({Intent.OUT_OF_DOMAIN})
    ),
    # From STATE_6_UPSELL
    Transition(
        State.STATE_6_UPSELL,
        State.STATE_7_END,
        frozenset({Intent.THANKYOU_SMALLTALK, Intent.PAYMENT_DELIVERY}),
    ),
    # From STATE_8_COMPLAINT
    Transition(
        State.STATE_8_COMPLAINT,
        State.STATE_7_END,
        frozenset({Intent.THANKYOU_SMALLTALK}),
    ),
    # From STATE_9_OOD (Out of Domain) - recovery transitions
    Transition(
        State.STATE_9_OOD,
        State.STATE_0_INIT,
        frozenset({Intent.GREETING_ONLY}),
    ),
    Transition(
        State.STATE_9_OOD,
        State.STATE_1_DISCOVERY,
        frozenset({Intent.DISCOVERY_OR_QUESTION}),
    ),
    # From STATE_7_END (End state) - restart transitions
    Transition(
        State.STATE_7_END,
        State.STATE_0_INIT,
        frozenset({Intent.GREETING_ONLY}),
    ),
    Transition(
        State.STATE_7_END,
        State.STATE_1_DISCOVERY,
        frozenset({Intent.DISCOVERY_OR_QUESTION}),
    ),
]


def get_possible_transitions(from_state: State) -> list[Transition]:
    """Get all possible transitions from a given state."""
    return [t for t in TRANSITIONS if t.from_state == from_state]


def get_next_state(current_state: State, intent: Intent) -> State:
    """
    Determine next state based on current state and intent.
    Returns current_state if no valid transition found.
    """
    for t in TRANSITIONS:
        if t.from_state == current_state and intent in t.when_intents:
            return t.to_state
    return current_state


# =============================================================================
# PLATFORM ALIASES (Telegram / ManyChat)
# =============================================================================


@dataclass
class PlatformKeyboard:
    """Quick reply buttons for a specific state."""

    buttons: list[list[str]]  # 2D grid of button texts
    one_time: bool = False


# Unified keyboard mapping for all platforms
def _coerce_keyboard_rows(value: Any) -> list[list[str]] | None:
    if not isinstance(value, list):
        return None
    rows: list[list[str]] = []
    for row in value:
        if isinstance(row, list) and all(isinstance(item, str) for item in row):
            rows.append(row)
    return rows if rows else None


def _load_state_keyboards() -> dict[State, PlatformKeyboard]:
    data = _load_state_machine_config()
    keyboards = data.get("keyboards", {})
    if not isinstance(keyboards, dict):
        return {}

    result: dict[State, PlatformKeyboard] = {}
    for state in State:
        rows = _coerce_keyboard_rows(keyboards.get(state.value))
        if rows:
            result[state] = PlatformKeyboard(buttons=rows)
    return result


def _load_escalation_keyboard() -> PlatformKeyboard:
    data = _load_state_machine_config()
    rows = _coerce_keyboard_rows(data.get("escalation_keyboard"))
    if rows:
        return PlatformKeyboard(buttons=rows, one_time=True)
    return PlatformKeyboard(buttons=[["Contact manager"]], one_time=True)


STATE_KEYBOARDS = _load_state_keyboards()
ESCALATION_KEYBOARD = _load_escalation_keyboard()


def get_keyboard_for_state(
    state: State, escalation_level: EscalationLevel = EscalationLevel.NONE
) -> PlatformKeyboard | None:
    """Get keyboard configuration for a state."""
    if escalation_level != EscalationLevel.NONE:
        return ESCALATION_KEYBOARD
    return STATE_KEYBOARDS.get(state)


# =============================================================================
# LEGACY ALIASES (for backward compatibility)
# =============================================================================

# Map old constants.py names to new State enum
LEGACY_STATE_ALIASES: dict[str, State] = {
    "STATE0_INIT": State.STATE_0_INIT,
    "STATE1_DISCOVERY": State.STATE_1_DISCOVERY,
    "STATE2_VISION": State.STATE_2_VISION,
    "STATE3_CLARIFY": State.STATE_3_SIZE_COLOR,  # renamed
    "STATE4_OFFER": State.STATE_4_OFFER,
    "STATE5_COMPARISON": State.STATE_5_PAYMENT_DELIVERY,  # renamed
    "STATE6_SIZING": State.STATE_6_UPSELL,  # renamed
    "STATE7_OBJECTION": State.STATE_7_END,  # renamed
    "STATE8_CHECKOUT": State.STATE_8_COMPLAINT,  # renamed
    "STATE9_OOD": State.STATE_9_OOD,
}


def normalize_state(value: str) -> State:
    """
    Normalize state string from any format to State enum.
    Handles legacy names, missing underscores, etc.
    """
    if not value:
        return State.STATE_0_INIT

    upper = value.upper().strip()

    # Check legacy aliases first
    if upper in LEGACY_STATE_ALIASES:
        if not settings.ENABLE_LEGACY_STATE_ALIASES:
            logger.error("Legacy state alias blocked: %s", upper)
            return State.STATE_0_INIT
        logger.warning(
            "Legacy state alias used: %s -> %s",
            upper,
            LEGACY_STATE_ALIASES[upper].value,
        )
        return LEGACY_STATE_ALIASES[upper]

    # Try direct parse
    return State.from_string(upper)

# Logger
logger = logging.getLogger(__name__)
