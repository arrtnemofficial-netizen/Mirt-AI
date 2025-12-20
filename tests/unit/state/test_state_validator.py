"""
Tests for state machine transitions and validation.
====================================================
Updated for new architecture with centralized state_machine.py
"""

from src.core.state_machine import (
    TRANSITIONS,
    Intent,
    State,
    get_next_state,
    get_possible_transitions,
    normalize_state,
)


# =============================================================================
# STATE TRANSITION TESTS
# =============================================================================


class TestStateTransitions:
    """Test FSM transition logic."""

    def test_init_to_discovery(self):
        """Test transition from INIT to DISCOVERY."""
        next_state = get_next_state(State.STATE_0_INIT, Intent.GREETING_ONLY)
        assert next_state == State.STATE_1_DISCOVERY

    def test_init_to_vision(self):
        """Test transition from INIT to VISION."""
        next_state = get_next_state(State.STATE_0_INIT, Intent.PHOTO_IDENT)
        assert next_state == State.STATE_2_VISION

    def test_init_to_size_color(self):
        """Test transition from INIT to SIZE_COLOR."""
        next_state = get_next_state(State.STATE_0_INIT, Intent.SIZE_HELP)
        assert next_state == State.STATE_3_SIZE_COLOR

    def test_init_to_payment(self):
        """Test transition from INIT to PAYMENT."""
        next_state = get_next_state(State.STATE_0_INIT, Intent.PAYMENT_DELIVERY)
        assert next_state == State.STATE_5_PAYMENT_DELIVERY

    def test_init_to_complaint(self):
        """Test transition from INIT to COMPLAINT."""
        next_state = get_next_state(State.STATE_0_INIT, Intent.COMPLAINT)
        assert next_state == State.STATE_8_COMPLAINT

    def test_init_to_end(self):
        """Test transition from INIT to END."""
        next_state = get_next_state(State.STATE_0_INIT, Intent.THANKYOU_SMALLTALK)
        assert next_state == State.STATE_7_END

    def test_init_to_ood(self):
        """Test transition from INIT to OOD."""
        next_state = get_next_state(State.STATE_0_INIT, Intent.OUT_OF_DOMAIN)
        assert next_state == State.STATE_9_OOD

    def test_discovery_to_vision(self):
        """Test transition from DISCOVERY to VISION."""
        next_state = get_next_state(State.STATE_1_DISCOVERY, Intent.PHOTO_IDENT)
        assert next_state == State.STATE_2_VISION

    def test_vision_to_size_color(self):
        """Test transition from VISION to SIZE_COLOR."""
        next_state = get_next_state(State.STATE_2_VISION, Intent.SIZE_HELP)
        assert next_state == State.STATE_3_SIZE_COLOR

    def test_size_color_to_offer(self):
        """Test transition from SIZE_COLOR to OFFER."""
        next_state = get_next_state(State.STATE_3_SIZE_COLOR, Intent.DISCOVERY_OR_QUESTION)
        assert next_state == State.STATE_4_OFFER

    def test_offer_to_payment(self):
        """Test transition from OFFER to PAYMENT."""
        next_state = get_next_state(State.STATE_4_OFFER, Intent.PAYMENT_DELIVERY)
        assert next_state == State.STATE_5_PAYMENT_DELIVERY

    def test_payment_to_upsell(self):
        """Test transition from PAYMENT to UPSELL."""
        next_state = get_next_state(State.STATE_5_PAYMENT_DELIVERY, Intent.PAYMENT_DELIVERY)
        assert next_state == State.STATE_6_UPSELL

    def test_upsell_to_end(self):
        """Test transition from UPSELL to END."""
        next_state = get_next_state(State.STATE_6_UPSELL, Intent.THANKYOU_SMALLTALK)
        assert next_state == State.STATE_7_END

    def test_no_transition_stays(self):
        """Test that invalid intent stays in current state."""
        next_state = get_next_state(State.STATE_4_OFFER, Intent.UNKNOWN_OR_EMPTY)
        assert next_state == State.STATE_4_OFFER


# =============================================================================
# TRANSITION MATRIX TESTS
# =============================================================================


class TestTransitionMatrix:
    """Test the transition matrix structure."""

    def test_transitions_not_empty(self):
        """Test that TRANSITIONS is not empty."""
        assert len(TRANSITIONS) > 0

    def test_all_transitions_have_required_fields(self):
        """Test that all transitions have required fields."""
        for transition in TRANSITIONS:
            assert transition.from_state is not None
            assert transition.to_state is not None
            assert len(transition.when_intents) > 0

    def test_get_possible_transitions(self):
        """Test getting possible transitions from a state."""
        transitions = get_possible_transitions(State.STATE_0_INIT)
        assert len(transitions) > 0

        # All transitions should be from STATE_0_INIT
        for t in transitions:
            assert t.from_state == State.STATE_0_INIT

    def test_all_states_have_transitions(self):
        """Test that all states have at least one transition."""
        from_states = {t.from_state for t in TRANSITIONS}
        expected_states = set(State)

        for state in expected_states:
            assert state in from_states, f"State {state} has no outgoing transitions"


# =============================================================================
# STATE NORMALIZATION TESTS
# =============================================================================


class TestStateNormalization:
    """Test state string normalization."""

    def test_normalize_standard_format(self):
        """Test normalizing standard state format."""
        state = normalize_state("STATE_0_INIT")
        assert state == State.STATE_0_INIT

    def test_normalize_legacy_format(self):
        """Test normalizing legacy format without underscore."""
        state = normalize_state("STATE0_INIT")
        assert state == State.STATE_0_INIT

        state = normalize_state("STATE1_DISCOVERY")
        assert state == State.STATE_1_DISCOVERY

    def test_normalize_lowercase(self):
        """Test normalizing lowercase."""
        state = normalize_state("state_0_init")
        assert state == State.STATE_0_INIT

    def test_normalize_empty_string(self):
        """Test normalizing empty string."""
        state = normalize_state("")
        assert state == State.STATE_0_INIT

    def test_normalize_none(self):
        """Test normalizing None."""
        state = normalize_state(None)
        assert state == State.STATE_0_INIT

    def test_normalize_invalid_state(self):
        """Test normalizing invalid state."""
        state = normalize_state("INVALID_STATE")
        assert state == State.STATE_0_INIT


# =============================================================================
# INTENT ENUM TESTS
# =============================================================================


class TestIntentEnum:
    """Test Intent enum functionality."""

    def test_intent_from_string_valid(self):
        """Test parsing valid intent."""
        intent = Intent.from_string("GREETING_ONLY")
        assert intent == Intent.GREETING_ONLY

    def test_intent_from_string_lowercase(self):
        """Test parsing lowercase intent."""
        intent = Intent.from_string("greeting_only")
        assert intent == Intent.GREETING_ONLY

    def test_intent_from_string_invalid(self):
        """Test parsing invalid intent."""
        intent = Intent.from_string("INVALID_INTENT")
        assert intent == Intent.UNKNOWN_OR_EMPTY


# =============================================================================
# STATE ENUM TESTS
# =============================================================================


class TestStateEnum:
    """Test State enum functionality."""

    def test_state_default(self):
        """Test default state."""
        assert State.default() == State.STATE_0_INIT

    def test_state_display_names(self):
        """Test display names for states."""
        assert State.STATE_0_INIT.display_name == "Початок"
        assert State.STATE_1_DISCOVERY.display_name == "Пошук"
        assert State.STATE_2_VISION.display_name == "Фото"

    def test_state_requires_escalation(self):
        """Test escalation requirement flags."""
        assert State.STATE_8_COMPLAINT.requires_escalation is True
        assert State.STATE_9_OOD.requires_escalation is True
        assert State.STATE_0_INIT.requires_escalation is False


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_complex_transition_path(self):
        """Test a complete conversation path."""
        # Start
        current = State.STATE_0_INIT

        # Greeting
        current = get_next_state(current, Intent.GREETING_ONLY)
        assert current == State.STATE_1_DISCOVERY

        # Photo
        current = get_next_state(current, Intent.PHOTO_IDENT)
        assert current == State.STATE_2_VISION

        # Size help
        current = get_next_state(current, Intent.SIZE_HELP)
        assert current == State.STATE_3_SIZE_COLOR

        # Discovery (ready for offer)
        current = get_next_state(current, Intent.DISCOVERY_OR_QUESTION)
        assert current == State.STATE_4_OFFER

    def test_escalation_states(self):
        """Test escalation states."""
        escalation_states = [s for s in State if s.requires_escalation]
        assert State.STATE_8_COMPLAINT in escalation_states
        assert State.STATE_9_OOD in escalation_states
        assert State.STATE_0_INIT not in escalation_states

    def test_all_intents_mapped(self):
        """Test that all intents are used in transitions."""
        used_intents = set()
        for transition in TRANSITIONS:
            used_intents.update(transition.when_intents)

        all_intents = set(Intent)
        # All intents except UNKNOWN_OR_EMPTY should be used
        usable_intents = all_intents - {Intent.UNKNOWN_OR_EMPTY}

        for intent in usable_intents:
            assert intent in used_intents, f"Intent {intent} is not used in any transition"
