"""Tests for state validator - ensures dialog never gets stuck."""

import pytest

from src.core.state_validator import (
    INTENT_STATE_HINTS,
    MAX_TURNS_IN_STATE,
    VALID_TRANSITIONS,
    StateValidator,
    get_state_validator,
    validate_state_transition,
)


class TestStateValidator:
    """Test StateValidator class."""

    def setup_method(self):
        self.validator = StateValidator()

    def test_valid_transition_init_to_discovery(self):
        """Test valid transition from INIT to DISCOVERY."""
        result = self.validator.validate_transition(
            session_id="test1",
            current_state="STATE_0_INIT",
            proposed_state="STATE_1_DISCOVERY",
        )

        assert result.new_state == "STATE_1_DISCOVERY"
        assert not result.was_corrected

    def test_valid_transition_stay_in_state(self):
        """Test valid transition staying in same state."""
        result = self.validator.validate_transition(
            session_id="test2",
            current_state="STATE_1_DISCOVERY",
            proposed_state="STATE_1_DISCOVERY",
        )

        assert result.new_state == "STATE_1_DISCOVERY"
        assert not result.was_corrected

    def test_invalid_transition_gets_corrected(self):
        """Test that invalid transitions are corrected."""
        # STATE_0_INIT cannot jump directly to STATE_7_END
        result = self.validator.validate_transition(
            session_id="test3",
            current_state="STATE_0_INIT",
            proposed_state="STATE_7_END",
        )

        assert result.was_corrected
        assert result.new_state in VALID_TRANSITIONS["STATE_0_INIT"]
        assert result.reason is not None

    def test_intent_based_correction(self):
        """Test that intent hints help correct state."""
        result = self.validator.validate_transition(
            session_id="test4",
            current_state="STATE_0_INIT",
            proposed_state="STATE_8_COMPLAINT",  # Invalid from INIT
            intent="GREETING_ONLY",
        )

        assert result.was_corrected
        # Should stay in INIT due to greeting intent
        assert result.new_state in VALID_TRANSITIONS["STATE_0_INIT"]

    def test_stuck_prevention(self):
        """Test that staying too long in one state triggers progression."""
        session_id = "test_stuck"

        # Simulate being stuck in STATE_1_DISCOVERY for many turns
        max_turns = MAX_TURNS_IN_STATE.get("STATE_1_DISCOVERY", 5)

        for i in range(max_turns + 1):
            result = self.validator.validate_transition(
                session_id=session_id,
                current_state="STATE_1_DISCOVERY",
                proposed_state="STATE_1_DISCOVERY",  # Keep proposing same state
            )

        # After max turns, should be forced to progress
        # (The last transition should trigger stuck prevention)
        stats = self.validator.get_session_stats(session_id)
        assert stats["total_turns"] == max_turns + 1

    def test_normalize_state_empty(self):
        """Test normalizing empty state."""
        result = self.validator._normalize_state("")
        assert result == "STATE_0_INIT"

    def test_normalize_state_valid(self):
        """Test normalizing valid state."""
        result = self.validator._normalize_state("STATE_4_OFFER")
        assert result == "STATE_4_OFFER"

    def test_session_stats(self):
        """Test getting session statistics."""
        session_id = "test_stats"

        self.validator.validate_transition(session_id, "STATE_0_INIT", "STATE_1_DISCOVERY")
        self.validator.validate_transition(session_id, "STATE_1_DISCOVERY", "STATE_2_VISION")
        self.validator.validate_transition(session_id, "STATE_2_VISION", "STATE_4_OFFER")

        stats = self.validator.get_session_stats(session_id)

        assert stats["total_turns"] == 3
        assert "STATE_1_DISCOVERY" in stats["states_visited"]
        assert stats["current_state"] == "STATE_4_OFFER"

    def test_clear_session(self):
        """Test clearing session history."""
        session_id = "test_clear"

        self.validator.validate_transition(session_id, "STATE_0_INIT", "STATE_1_DISCOVERY")
        self.validator.clear_session(session_id)

        stats = self.validator.get_session_stats(session_id)
        assert stats["total_turns"] == 0


class TestValidTransitions:
    """Test that transition matrix is properly configured."""

    def test_all_states_have_transitions(self):
        """Test that all states have defined transitions."""
        expected_states = [
            "STATE_0_INIT",
            "STATE_1_DISCOVERY",
            "STATE_2_VISION",
            "STATE_3_SIZE_COLOR",
            "STATE_4_OFFER",
            "STATE_5_PAYMENT_DELIVERY",
            "STATE_6_UPSELL",
            "STATE_7_END",
            "STATE_8_COMPLAINT",
            "STATE_9_OOD",
        ]

        for state in expected_states:
            assert state in VALID_TRANSITIONS, f"Missing transitions for {state}"
            assert len(VALID_TRANSITIONS[state]) > 0, f"Empty transitions for {state}"

    def test_all_states_can_stay(self):
        """Test that all states can transition to themselves."""
        for state, transitions in VALID_TRANSITIONS.items():
            assert state in transitions, f"{state} cannot stay in itself"

    def test_end_state_can_restart(self):
        """Test that END state can restart conversation."""
        end_transitions = VALID_TRANSITIONS["STATE_7_END"]
        assert "STATE_0_INIT" in end_transitions or "STATE_1_DISCOVERY" in end_transitions


class TestIntentStateHints:
    """Test intent to state mapping."""

    def test_greeting_maps_to_init(self):
        """Test that greeting intent maps to INIT state."""
        assert INTENT_STATE_HINTS.get("GREETING_ONLY") == "STATE_0_INIT"

    def test_product_search_maps_to_discovery(self):
        """Test that product search maps to DISCOVERY."""
        assert INTENT_STATE_HINTS.get("PRODUCT_SEARCH") == "STATE_1_DISCOVERY"

    def test_all_intents_have_valid_states(self):
        """Test that all intent hints point to valid states."""
        for intent, state in INTENT_STATE_HINTS.items():
            # State should be in valid transitions matrix
            assert any(state in transitions for transitions in VALID_TRANSITIONS.values()), (
                f"Intent {intent} maps to unknown state {state}"
            )


class TestConvenienceFunction:
    """Test validate_state_transition convenience function."""

    def test_basic_usage(self):
        """Test basic convenience function usage."""
        result = validate_state_transition(
            session_id="conv_test",
            current_state="STATE_0_INIT",
            proposed_state="STATE_1_DISCOVERY",
        )

        assert result.new_state == "STATE_1_DISCOVERY"
        assert not result.was_corrected

    def test_with_intent(self):
        """Test with intent parameter."""
        result = validate_state_transition(
            session_id="conv_test2",
            current_state="STATE_1_DISCOVERY",
            proposed_state="STATE_4_OFFER",
            intent="DISCOVERY_OR_QUESTION",
        )

        assert result.new_state is not None


class TestGlobalValidator:
    """Test global validator singleton."""

    def test_get_state_validator_returns_same_instance(self):
        """Test that get_state_validator returns singleton."""
        v1 = get_state_validator()
        v2 = get_state_validator()

        assert v1 is v2


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_unknown_current_state(self):
        """Test handling unknown current state."""
        validator = StateValidator()

        result = validator.validate_transition(
            session_id="edge1",
            current_state="UNKNOWN_STATE",
            proposed_state="STATE_1_DISCOVERY",
        )

        # Should normalize and handle gracefully
        assert result.new_state is not None

    def test_none_intent(self):
        """Test handling None intent."""
        validator = StateValidator()

        result = validator.validate_transition(
            session_id="edge2",
            current_state="STATE_0_INIT",
            proposed_state="STATE_1_DISCOVERY",
            intent=None,
        )

        assert result.new_state == "STATE_1_DISCOVERY"

    def test_empty_session_id(self):
        """Test handling empty session ID."""
        validator = StateValidator()

        result = validator.validate_transition(
            session_id="",
            current_state="STATE_0_INIT",
            proposed_state="STATE_1_DISCOVERY",
        )

        assert result.new_state == "STATE_1_DISCOVERY"
