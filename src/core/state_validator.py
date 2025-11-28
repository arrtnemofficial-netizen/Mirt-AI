"""State transition validator to ensure dialog never gets stuck.

Validates and corrects state transitions to guarantee conversation flow.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from src.core.state_machine import Intent, State


logger = logging.getLogger(__name__)


class TransitionResult(NamedTuple):
    """Result of state transition validation."""

    new_state: str
    was_corrected: bool
    reason: str | None


# Valid state transitions matrix (matches State enum in state_machine.py)
# States: STATE_0_INIT, STATE_1_DISCOVERY, STATE_2_VISION, STATE_3_SIZE_COLOR,
#         STATE_4_OFFER, STATE_5_PAYMENT_DELIVERY, STATE_6_UPSELL, STATE_7_END,
#         STATE_8_COMPLAINT, STATE_9_OOD
VALID_TRANSITIONS: dict[str, set[str]] = {
    "STATE_0_INIT": {
        "STATE_0_INIT",  # Stay for greetings
        "STATE_1_DISCOVERY",  # Move to discovery
        "STATE_9_OOD",  # Out of domain
    },
    "STATE_1_DISCOVERY": {
        "STATE_1_DISCOVERY",  # Stay for more questions
        "STATE_2_VISION",  # Show products (vision)
        "STATE_3_SIZE_COLOR",  # Discuss size/color
        "STATE_4_OFFER",  # Direct to offer if clear
        "STATE_0_INIT",  # Reset on new topic
    },
    "STATE_2_VISION": {
        "STATE_2_VISION",  # Stay for more viewing
        "STATE_1_DISCOVERY",  # Back to discovery
        "STATE_3_SIZE_COLOR",  # Discuss details
        "STATE_4_OFFER",  # Move to offer
    },
    "STATE_3_SIZE_COLOR": {
        "STATE_3_SIZE_COLOR",  # Stay for more details
        "STATE_2_VISION",  # Back to vision
        "STATE_4_OFFER",  # Move to offer
        "STATE_1_DISCOVERY",  # Back to discovery
    },
    "STATE_4_OFFER": {
        "STATE_4_OFFER",  # Stay for more offers
        "STATE_3_SIZE_COLOR",  # Back to size/color
        "STATE_5_PAYMENT_DELIVERY",  # Payment questions
        "STATE_6_UPSELL",  # Upsell
        "STATE_7_END",  # Close deal
        "STATE_8_COMPLAINT",  # Handle complaints
    },
    "STATE_5_PAYMENT_DELIVERY": {
        "STATE_5_PAYMENT_DELIVERY",  # Stay for payment Q
        "STATE_4_OFFER",  # Back to offer
        "STATE_7_END",  # Close
    },
    "STATE_6_UPSELL": {
        "STATE_6_UPSELL",  # Stay for upsell
        "STATE_4_OFFER",  # Back to offer
        "STATE_7_END",  # Close
    },
    "STATE_7_END": {
        "STATE_7_END",  # Stay in end
        "STATE_0_INIT",  # New conversation
        "STATE_1_DISCOVERY",  # New product search
    },
    "STATE_8_COMPLAINT": {
        "STATE_8_COMPLAINT",  # Handle complaint
        "STATE_4_OFFER",  # Back to offer
        "STATE_7_END",  # End
    },
    "STATE_9_OOD": {
        "STATE_9_OOD",  # Stay OOD
        "STATE_0_INIT",  # Back to init
        "STATE_1_DISCOVERY",  # Try discovery
    },
}

# Intent to suggested state mapping (using correct state names)
INTENT_STATE_HINTS: dict[str, str] = {
    "GREETING_ONLY": "STATE_0_INIT",
    "PRODUCT_SEARCH": "STATE_1_DISCOVERY",
    "PRODUCT_QUESTION": "STATE_1_DISCOVERY",
    "DISCOVERY_OR_QUESTION": "STATE_1_DISCOVERY",
    "SIZE_QUESTION": "STATE_3_SIZE_COLOR",
    "SIZE_HELP": "STATE_3_SIZE_COLOR",
    "COLOR_HELP": "STATE_3_SIZE_COLOR",
    "PRICE_QUESTION": "STATE_4_OFFER",
    "PHOTO_IDENT": "STATE_2_VISION",
    "AVAILABILITY_QUESTION": "STATE_4_OFFER",
    "COMPARISON_REQUEST": "STATE_2_VISION",
    "POSITIVE_FEEDBACK": "STATE_4_OFFER",
    "READY_TO_BUY": "STATE_5_PAYMENT_DELIVERY",
    "PAYMENT_DELIVERY": "STATE_5_PAYMENT_DELIVERY",
    "OBJECTION_PRICE": "STATE_4_OFFER",
    "OBJECTION_QUALITY": "STATE_4_OFFER",
    "OBJECTION_DELIVERY": "STATE_5_PAYMENT_DELIVERY",
    "REQUEST_DISCOUNT": "STATE_4_OFFER",
    "ORDER_INTENT": "STATE_5_PAYMENT_DELIVERY",
    "FAREWELL": "STATE_7_END",
    "THANKYOU_SMALLTALK": "STATE_7_END",
    "COMPLAINT": "STATE_8_COMPLAINT",
    "OFF_TOPIC": "STATE_9_OOD",
    "OUT_OF_DOMAIN": "STATE_9_OOD",
    "UNCLEAR": "STATE_1_DISCOVERY",
    "UNKNOWN_OR_EMPTY": "STATE_1_DISCOVERY",
}

# Maximum turns in same state before forcing progression
MAX_TURNS_IN_STATE: dict[str, int] = {
    "STATE_0_INIT": 2,
    "STATE_1_DISCOVERY": 5,
    "STATE_2_VISION": 4,
    "STATE_3_SIZE_COLOR": 4,
    "STATE_4_OFFER": 4,
    "STATE_5_PAYMENT_DELIVERY": 3,
    "STATE_6_UPSELL": 3,
    "STATE_7_END": 2,
    "STATE_8_COMPLAINT": 3,
    "STATE_9_OOD": 2,
}


class StateValidator:
    """Validates and corrects state transitions."""

    def __init__(self):
        self.state_history: dict[str, list[str]] = {}  # session_id -> states

    def validate_transition(
        self,
        session_id: str,
        current_state: str,
        proposed_state: str,
        intent: str | None = None,
    ) -> TransitionResult:
        """
        Validate and potentially correct a state transition.

        Args:
            session_id: Session identifier
            current_state: Current conversation state
            proposed_state: State proposed by LLM
            intent: Detected user intent

        Returns:
            TransitionResult with validated/corrected state
        """
        # Normalize states
        current = self._normalize_state(current_state)
        proposed = self._normalize_state(proposed_state)

        # Track history
        if session_id not in self.state_history:
            self.state_history[session_id] = []
        history = self.state_history[session_id]

        # Check if transition is valid
        valid_next = VALID_TRANSITIONS.get(current, set())

        if proposed in valid_next:
            # Valid transition
            history.append(proposed)
            return TransitionResult(proposed, False, None)

        # Invalid transition - try to correct
        corrected, reason = self._correct_transition(current, proposed, intent, history)

        history.append(corrected)
        logger.warning(
            "Corrected state transition: %s -> %s (was: %s). Reason: %s",
            current,
            corrected,
            proposed,
            reason,
        )

        return TransitionResult(corrected, True, reason)

    def _normalize_state(self, state: str) -> str:
        """Normalize state string to canonical form."""
        if not state:
            return "STATE_0_INIT"

        state = state.upper().strip()

        # Handle various formats
        if state.startswith("STATE"):
            return state

        # Try to parse from State enum
        try:
            return State.from_string(state).value
        except (ValueError, KeyError):
            return "STATE_0_INIT"

    def _correct_transition(
        self,
        current: str,
        proposed: str,
        intent: str | None,
        history: list[str],
    ) -> tuple[str, str]:
        """Determine correct state when proposed is invalid."""

        # Strategy 1: Use intent hint
        if intent and intent in INTENT_STATE_HINTS:
            hint = INTENT_STATE_HINTS[intent]
            valid_next = VALID_TRANSITIONS.get(current, set())
            if hint in valid_next:
                return hint, f"Intent-based correction ({intent})"

        # Strategy 2: Check for stuck state
        if history:
            same_state_count = 0
            for h in reversed(history):
                if h == current:
                    same_state_count += 1
                else:
                    break

            max_turns = MAX_TURNS_IN_STATE.get(current, 3)
            if same_state_count >= max_turns:
                # Force progression
                next_state = self._get_next_progression(current)
                return next_state, f"Stuck prevention (>{max_turns} turns)"

        # Strategy 3: Find closest valid state
        valid_next = VALID_TRANSITIONS.get(current, set())
        if valid_next:
            # Prefer staying in current state
            if current in valid_next:
                return current, "Stay in current state"
            # Otherwise pick first valid
            return list(valid_next)[0], "Fallback to valid transition"

        # Strategy 4: Default progression
        return self._get_next_progression(current), "Default progression"

    def _get_next_progression(self, current: str) -> str:
        """Get natural next state for progression."""
        progression = {
            "STATE_0_INIT": "STATE_1_DISCOVERY",
            "STATE_1_DISCOVERY": "STATE_2_VISION",
            "STATE_2_VISION": "STATE_3_SIZE_COLOR",
            "STATE_3_SIZE_COLOR": "STATE_4_OFFER",
            "STATE_4_OFFER": "STATE_5_PAYMENT_DELIVERY",
            "STATE_5_PAYMENT_DELIVERY": "STATE_7_END",
            "STATE_6_UPSELL": "STATE_7_END",
            "STATE_7_END": "STATE_0_INIT",
            "STATE_8_COMPLAINT": "STATE_4_OFFER",
            "STATE_9_OOD": "STATE_0_INIT",
        }
        return progression.get(current, "STATE_1_DISCOVERY")

    def get_session_stats(self, session_id: str) -> dict:
        """Get statistics for a session."""
        history = self.state_history.get(session_id, [])
        return {
            "total_turns": len(history),
            "states_visited": list(set(history)),
            "current_state": history[-1] if history else "STATE_0_INIT",
            "state_counts": {s: history.count(s) for s in set(history)},
        }

    def clear_session(self, session_id: str) -> None:
        """Clear session history."""
        self.state_history.pop(session_id, None)


# Global validator instance
_validator: StateValidator | None = None


def get_state_validator() -> StateValidator:
    """Get or create global state validator."""
    global _validator
    if _validator is None:
        _validator = StateValidator()
    return _validator


def validate_state_transition(
    session_id: str,
    current_state: str,
    proposed_state: str,
    intent: str | None = None,
) -> TransitionResult:
    """Convenience function for state validation."""
    validator = get_state_validator()
    return validator.validate_transition(session_id, current_state, proposed_state, intent)
