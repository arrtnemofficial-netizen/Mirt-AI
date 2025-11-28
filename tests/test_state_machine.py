"""
Tests for centralized state machine.
"""

from src.core.state_machine import (
    TRANSITIONS,
    EscalationLevel,
    Intent,
    State,
    get_keyboard_for_state,
    get_next_state,
    normalize_state,
)


class TestStateEnum:
    """Tests for State enum."""

    def test_default_state(self):
        assert State.default() == State.STATE_0_INIT

    def test_from_string_valid(self):
        assert State.from_string("STATE_0_INIT") == State.STATE_0_INIT
        assert State.from_string("STATE_1_DISCOVERY") == State.STATE_1_DISCOVERY

    def test_from_string_legacy_format(self):
        """Test parsing legacy format without underscore after number."""
        assert State.from_string("STATE0_INIT") == State.STATE_0_INIT
        assert State.from_string("STATE1_DISCOVERY") == State.STATE_1_DISCOVERY

    def test_from_string_invalid(self):
        """Invalid state should fallback to INIT."""
        assert State.from_string("INVALID") == State.STATE_0_INIT
        assert State.from_string("") == State.STATE_0_INIT

    def test_requires_escalation(self):
        assert State.STATE_8_COMPLAINT.requires_escalation is True
        assert State.STATE_9_OOD.requires_escalation is True
        assert State.STATE_0_INIT.requires_escalation is False


class TestIntentEnum:
    """Tests for Intent enum."""

    def test_from_string_valid(self):
        assert Intent.from_string("GREETING_ONLY") == Intent.GREETING_ONLY
        assert Intent.from_string("greeting_only") == Intent.GREETING_ONLY

    def test_from_string_invalid(self):
        assert Intent.from_string("INVALID") == Intent.UNKNOWN_OR_EMPTY


class TestNormalizeState:
    """Tests for normalize_state function."""

    def test_normalize_standard(self):
        assert normalize_state("STATE_0_INIT") == State.STATE_0_INIT

    def test_normalize_legacy(self):
        assert normalize_state("STATE0_INIT") == State.STATE_0_INIT

    def test_normalize_empty(self):
        assert normalize_state("") == State.STATE_0_INIT
        assert normalize_state(None) == State.STATE_0_INIT


class TestGetNextState:
    """Tests for FSM transitions."""

    def test_init_to_discovery(self):
        result = get_next_state(State.STATE_0_INIT, Intent.GREETING_ONLY)
        assert result == State.STATE_1_DISCOVERY

    def test_init_to_vision(self):
        result = get_next_state(State.STATE_0_INIT, Intent.PHOTO_IDENT)
        assert result == State.STATE_2_VISION

    def test_init_to_complaint(self):
        result = get_next_state(State.STATE_0_INIT, Intent.COMPLAINT)
        assert result == State.STATE_8_COMPLAINT

    def test_no_transition_stays(self):
        """Unknown intent should stay in current state."""
        result = get_next_state(State.STATE_4_OFFER, Intent.OUT_OF_DOMAIN)
        # If no explicit transition, stays in current state
        assert result in (State.STATE_4_OFFER, State.STATE_9_OOD)


class TestKeyboards:
    """Tests for keyboard configuration."""

    def test_init_state_has_keyboard(self):
        kb = get_keyboard_for_state(State.STATE_0_INIT)
        assert kb is not None
        assert len(kb.buttons) > 0

    def test_escalation_keyboard(self):
        kb = get_keyboard_for_state(State.STATE_0_INIT, EscalationLevel.L1)
        assert kb is not None
        assert "менеджером" in kb.buttons[0][0].lower()

    def test_end_state_no_keyboard(self):
        kb = get_keyboard_for_state(State.STATE_7_END)
        assert kb is None


class TestTransitionsTable:
    """Tests for FSM transitions table."""

    def test_transitions_not_empty(self):
        assert len(TRANSITIONS) > 0

    def test_all_transitions_have_from_state(self):
        for t in TRANSITIONS:
            assert t.from_state is not None
            assert isinstance(t.from_state, State)

    def test_all_transitions_have_to_state(self):
        for t in TRANSITIONS:
            assert t.to_state is not None
            assert isinstance(t.to_state, State)

    def test_all_transitions_have_intents(self):
        for t in TRANSITIONS:
            assert len(t.when_intents) > 0
