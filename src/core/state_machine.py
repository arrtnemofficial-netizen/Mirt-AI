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


# =============================================================================
# STATES (Single Source of Truth)
# =============================================================================


class State(str, Enum):
    """
    Agent conversation states.
    Names match system_prompt_full.yaml exactly.
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


# Display names for UI/logs
STATE_DISPLAY_NAMES: dict[State, str] = {
    State.STATE_0_INIT: "Початок",
    State.STATE_1_DISCOVERY: "Пошук",
    State.STATE_2_VISION: "Фото",
    State.STATE_3_SIZE_COLOR: "Розмір/Колір",
    State.STATE_4_OFFER: "Пропозиція",
    State.STATE_5_PAYMENT_DELIVERY: "Оплата/Доставка",
    State.STATE_6_UPSELL: "Допродаж",
    State.STATE_7_END: "Завершення",
    State.STATE_8_COMPLAINT: "Скарга",
    State.STATE_9_OOD: "Поза доменом",
}


# =============================================================================
# INTENTS (Single Source of Truth)
# =============================================================================


class Intent(str, Enum):
    """
    User intent classification labels.
    Matches INTENT_LABELS in system_prompt_full.yaml.
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


# FSM Transition Table - extracted from system_prompt_full.yaml
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
        "зріст/вік відомі і тип речі зрозумілий",
    ),
    Transition(State.STATE_1_DISCOVERY, State.STATE_2_VISION, frozenset({Intent.PHOTO_IDENT})),
    Transition(State.STATE_1_DISCOVERY, State.STATE_9_OOD, frozenset({Intent.OUT_OF_DOMAIN})),
    # From STATE_2_VISION
    Transition(
        State.STATE_2_VISION,
        State.STATE_3_SIZE_COLOR,
        frozenset({Intent.SIZE_HELP, Intent.COLOR_HELP, Intent.DISCOVERY_OR_QUESTION}),
        "модель знайдена",
    ),
    Transition(
        State.STATE_2_VISION,
        State.STATE_9_OOD,
        frozenset({Intent.OUT_OF_DOMAIN}),
        "на фото явно не одяг",
    ),
    # From STATE_3_SIZE_COLOR
    Transition(
        State.STATE_3_SIZE_COLOR,
        State.STATE_4_OFFER,
        frozenset({Intent.DISCOVERY_OR_QUESTION, Intent.SIZE_HELP, Intent.COLOR_HELP}),
        "є продукт, розмір та колір",
    ),
    Transition(
        State.STATE_3_SIZE_COLOR,
        State.STATE_9_OOD,
        frozenset({Intent.OUT_OF_DOMAIN}),
        "розмір поза межами доступних",
    ),
    # From STATE_4_OFFER
    Transition(
        State.STATE_4_OFFER,
        State.STATE_5_PAYMENT_DELIVERY,
        frozenset({Intent.PAYMENT_DELIVERY}),
        "клієнт готовий оформлювати",
    ),
    Transition(
        State.STATE_4_OFFER,
        State.STATE_7_END,
        frozenset({Intent.THANKYOU_SMALLTALK}),
        "клієнт відмовився",
    ),
    # From STATE_5_PAYMENT_DELIVERY
    Transition(
        State.STATE_5_PAYMENT_DELIVERY,
        State.STATE_6_UPSELL,
        frozenset({Intent.PAYMENT_DELIVERY}),
        "оплата підтверджена, upsell доречний",
    ),
    Transition(
        State.STATE_5_PAYMENT_DELIVERY,
        State.STATE_7_END,
        frozenset({Intent.PAYMENT_DELIVERY, Intent.THANKYOU_SMALLTALK}),
        "оплата підтверджена, upsell недоречний",
    ),
    Transition(
        State.STATE_5_PAYMENT_DELIVERY, State.STATE_9_OOD, frozenset({Intent.OUT_OF_DOMAIN})
    ),
    # From STATE_6_UPSELL
    Transition(
        State.STATE_6_UPSELL,
        State.STATE_7_END,
        frozenset({Intent.THANKYOU_SMALLTALK, Intent.PAYMENT_DELIVERY}),
        "клієнт підтвердив або відмовився",
    ),
    # From STATE_8_COMPLAINT
    Transition(
        State.STATE_8_COMPLAINT,
        State.STATE_7_END,
        frozenset({Intent.THANKYOU_SMALLTALK}),
        "ескалація зафіксована",
    ),
    # From STATE_9_OOD (Out of Domain) - recovery transitions
    Transition(
        State.STATE_9_OOD,
        State.STATE_0_INIT,
        frozenset({Intent.GREETING_ONLY}),
        "відновлення після out-of-domain",
    ),
    Transition(
        State.STATE_9_OOD,
        State.STATE_1_DISCOVERY,
        frozenset({Intent.DISCOVERY_OR_QUESTION}),
        "повернення до пошуку",
    ),
    # From STATE_7_END (End state) - restart transitions
    Transition(
        State.STATE_7_END,
        State.STATE_0_INIT,
        frozenset({Intent.GREETING_ONLY}),
        "перезапуск розмови",
    ),
    Transition(
        State.STATE_7_END,
        State.STATE_1_DISCOVERY,
        frozenset({Intent.DISCOVERY_OR_QUESTION}),
        "почати новий пошук",
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
STATE_KEYBOARDS: dict[State, PlatformKeyboard] = {
    State.STATE_0_INIT: PlatformKeyboard(
        [
            ["👗 Сукні", "👔 Костюми"],
            ["🧥 Тренчі", "📏 Розмірна сітка"],
        ]
    ),
    State.STATE_1_DISCOVERY: PlatformKeyboard(
        [
            ["👗 Сукні", "👔 Костюми"],
            ["🧥 Тренчі", "📏 Розмірна сітка"],
        ]
    ),
    State.STATE_2_VISION: PlatformKeyboard(
        [
            ["🎨 Інші кольори", "📏 Який розмір?"],
        ]
    ),
    State.STATE_3_SIZE_COLOR: PlatformKeyboard(
        [
            ["📏 Розмірна сітка", "🎨 Інші кольори"],
            ["✅ Підходить!"],
        ]
    ),
    State.STATE_4_OFFER: PlatformKeyboard(
        [
            ["✅ Беру!", "🎨 Інший колір"],
            ["📏 Інший розмір", "❓ Ще питання"],
        ]
    ),
    State.STATE_5_PAYMENT_DELIVERY: PlatformKeyboard(
        [
            ["💳 Повна оплата", "💵 Передплата 200 грн"],
        ]
    ),
    State.STATE_6_UPSELL: PlatformKeyboard(
        [
            ["✅ Так, додати", "❌ Ні, дякую"],
        ]
    ),
    # STATE_7_END, STATE_8_COMPLAINT, STATE_9_OOD - no keyboards (or escalation)
}

ESCALATION_KEYBOARD = PlatformKeyboard(
    [
        ["👩 Зв'язок з менеджером"],
    ],
    one_time=True,
)


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
        return LEGACY_STATE_ALIASES[upper]

    # Try direct parse
    return State.from_string(upper)

