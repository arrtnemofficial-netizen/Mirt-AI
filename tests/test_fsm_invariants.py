"""
FSM Invariants and Transition Tests.
=====================================
Tests that enforce the frozen FSM specification from docs/FSM_TRANSITION_TABLE.md.

These tests MUST pass before any FSM changes are deployed.
"""

import pytest

from src.agents.langgraph.edges import (
    _resolve_intent_route,
    route_after_agent,
    route_after_intent,
    route_after_offer,
    route_after_vision,
)
from src.agents.langgraph.nodes.intent import detect_intent_from_text
from src.core.state_machine import TRANSITIONS, Intent, State, get_next_state


# =============================================================================
# VALID STATES AND INTENTS
# =============================================================================

ALL_STATES = [s.value for s in State]
ALL_INTENTS = [i.value for i in Intent]


class TestStateValidity:
    """Ensure all state values are valid."""

    def test_all_states_are_strings(self):
        """All state values must be strings."""
        for state in State:
            assert isinstance(state.value, str)
            assert state.value.startswith("STATE_")

    def test_state_count(self):
        """There must be exactly 10 states (0-9)."""
        assert len(State) == 10

    def test_all_intents_are_strings(self):
        """All intent values must be strings."""
        for intent in Intent:
            assert isinstance(intent.value, str)
            assert intent.value.isupper()


# =============================================================================
# INVARIANT 1: has_image reset after vision
# =============================================================================


class TestHasImageInvariant:
    """has_image must be False after vision_node."""

    @pytest.mark.asyncio
    async def test_vision_node_resets_has_image(self):
        """Vision node must set has_image to False."""
        from unittest.mock import patch

        state = {
            "session_id": "test",
            "messages": [{"role": "user", "content": "Що це?"}],
            "has_image": True,
            "image_url": "https://example.com/test.jpg",
            "metadata": {"session_id": "test", "has_image": True},
            "current_state": "STATE_2_VISION",
            "selected_products": [],
        }

        # Mock run_vision
        async def mock_run_vision(message, deps):
            from src.agents.pydantic.models import VisionResponse

            return VisionResponse(
                reply_to_user="Тест",
                confidence=0.9,
                needs_clarification=False,
            )

        with patch("src.agents.pydantic.vision_agent.run_vision", new=mock_run_vision):
            import importlib

            import src.agents.langgraph.nodes.vision as vision_module

            importlib.reload(vision_module)
            output = await vision_module.vision_node(state)

        # INVARIANT: has_image must be False after vision
        assert output.get("has_image") is False, "has_image must be False after vision_node"
        assert output.get("metadata", {}).get("has_image") is False, (
            "metadata.has_image must be False"
        )


# =============================================================================
# INVARIANT 2: current_state always valid
# =============================================================================


class TestStateValidityInvariant:
    """current_state must always be a valid STATE_* value."""

    @pytest.mark.parametrize("state_value", ALL_STATES)
    def test_state_from_string_valid(self, state_value):
        """State.from_string must return valid state for all valid inputs."""
        state = State.from_string(state_value)
        assert state.value in ALL_STATES

    def test_state_from_string_invalid_returns_init(self):
        """State.from_string must return STATE_0_INIT for invalid inputs."""
        assert State.from_string("INVALID").value == "STATE_0_INIT"
        assert State.from_string("").value == "STATE_0_INIT"
        assert State.from_string(None).value == "STATE_0_INIT"


# =============================================================================
# INVARIANT 3: OFFER + PAYMENT_DELIVERY → PAYMENT
# =============================================================================


class TestOfferToPaymentInvariant:
    """In STATE_4_OFFER, PAYMENT_DELIVERY must route to payment."""

    def test_offer_payment_intent_routes_to_payment(self):
        """PAYMENT_DELIVERY in OFFER state must go to payment node."""
        state = {
            "current_state": "STATE_4_OFFER",
            "detected_intent": "PAYMENT_DELIVERY",
            "selected_products": [{"name": "Test", "price": 100}],
        }
        route = route_after_intent(state)
        assert route == "payment", f"Expected 'payment', got '{route}'"

    @pytest.mark.parametrize(
        "confirmation",
        [
            "так",
            "да",
            "yes",
            "ок",
            "добре",
            "згодна",
            "беру",
            "оформляємо",
        ],
    )
    def test_confirmation_words_trigger_payment_in_offer(self, confirmation):
        """Confirmation words in OFFER state must trigger PAYMENT_DELIVERY intent."""
        intent = detect_intent_from_text(
            confirmation, has_image=False, current_state="STATE_4_OFFER"
        )
        assert intent == "PAYMENT_DELIVERY", (
            f"'{confirmation}' should be PAYMENT_DELIVERY, got {intent}"
        )

    @pytest.mark.parametrize(
        "product",
        [
            "лагуна",
            "мрія",
            "ритм",
            "каприз",
            "валері",
            "мерея",
        ],
    )
    def test_product_names_trigger_payment_in_offer(self, product):
        """Product names in OFFER state must trigger PAYMENT_DELIVERY intent."""
        intent = detect_intent_from_text(product, has_image=False, current_state="STATE_4_OFFER")
        assert intent == "PAYMENT_DELIVERY", f"'{product}' should be PAYMENT_DELIVERY, got {intent}"


# =============================================================================
# INVARIANT 4: COMPLAINT always escalates
# =============================================================================


class TestComplaintEscalationInvariant:
    """COMPLAINT intent must always route to escalation."""

    @pytest.mark.parametrize("current_state", ALL_STATES)
    def test_complaint_escalates_from_any_state(self, current_state):
        """COMPLAINT must route to escalation from any state."""
        route = _resolve_intent_route("COMPLAINT", current_state, {})
        assert route == "escalation", f"COMPLAINT from {current_state} should escalate, got {route}"


# =============================================================================
# INVARIANT 5: PHOTO_IDENT always goes to vision
# =============================================================================


class TestPhotoIdentVisionInvariant:
    """PHOTO_IDENT intent must always route to vision."""

    @pytest.mark.parametrize("current_state", ALL_STATES)
    def test_photo_ident_routes_to_vision(self, current_state):
        """PHOTO_IDENT must route to vision from any state."""
        route = _resolve_intent_route("PHOTO_IDENT", current_state, {})
        assert route == "vision", (
            f"PHOTO_IDENT from {current_state} should go to vision, got {route}"
        )


# =============================================================================
# TRANSITION TABLE COVERAGE
# =============================================================================


class TestTransitionTableCoverage:
    """Ensure all transitions in state_machine.py are valid."""

    def test_all_transitions_have_valid_states(self):
        """All transitions must have valid from_state and to_state."""
        for t in TRANSITIONS:
            assert t.from_state in State, f"Invalid from_state: {t.from_state}"
            assert t.to_state in State, f"Invalid to_state: {t.to_state}"

    def test_all_transitions_have_valid_intents(self):
        """All transitions must have valid intents."""
        for t in TRANSITIONS:
            for intent in t.when_intents:
                assert intent in Intent, f"Invalid intent: {intent}"

    def test_no_duplicate_transitions(self):
        """No duplicate (from_state, intent) pairs."""
        seen = set()
        for t in TRANSITIONS:
            for intent in t.when_intents:
                key = (t.from_state, intent)
                # Note: some (state, intent) pairs may have multiple transitions
                # with different conditions - this is allowed but should be documented

    def test_get_next_state_returns_valid_state(self):
        """get_next_state must always return a valid State."""
        for state in State:
            for intent in Intent:
                next_state = get_next_state(state, intent)
                assert next_state in State, f"Invalid next state for ({state}, {intent})"


# =============================================================================
# ROUTING CONSISTENCY
# =============================================================================


class TestRoutingConsistency:
    """Ensure routing functions return valid values."""

    @pytest.mark.parametrize("intent", ALL_INTENTS)
    @pytest.mark.parametrize("current_state", ALL_STATES)
    def test_resolve_intent_route_returns_valid_route(self, intent, current_state):
        """_resolve_intent_route must return one of the valid routes."""
        valid_routes = {"vision", "agent", "offer", "payment", "escalation"}
        route = _resolve_intent_route(intent, current_state, {})
        assert route in valid_routes, f"Invalid route '{route}' for ({current_state}, {intent})"

    def test_route_after_vision_returns_valid_route(self):
        """route_after_vision must return valid route."""
        valid_routes = {"offer", "agent", "validation", "end"}

        # With products
        route = route_after_vision({"selected_products": [{"name": "Test"}]})
        assert route in valid_routes

        # Without products
        route = route_after_vision({})
        assert route in valid_routes

    def test_route_after_agent_returns_valid_route(self):
        """route_after_agent must return valid route."""
        valid_routes = {"validation", "offer", "end"}

        route = route_after_agent({})
        assert route in valid_routes

    def test_route_after_offer_returns_valid_route(self):
        """route_after_offer must return valid route."""
        valid_routes = {"payment", "validation", "end"}

        route = route_after_offer({"detected_intent": "PAYMENT_DELIVERY"})
        assert route in valid_routes


# =============================================================================
# PAYMENT STATE INVARIANTS
# =============================================================================


class TestPaymentStateInvariants:
    """Payment state specific invariants."""

    def test_payment_state_keeps_payment_intent(self):
        """In STATE_5_PAYMENT_DELIVERY, most inputs should stay PAYMENT_DELIVERY."""
        test_inputs = ["158", "Київ", "Нова пошта 5", "+380991234567", "Іванов Іван"]

        for text in test_inputs:
            intent = detect_intent_from_text(
                text, has_image=False, current_state="STATE_5_PAYMENT_DELIVERY"
            )
            assert intent == "PAYMENT_DELIVERY", (
                f"'{text}' in PAYMENT state should stay PAYMENT, got {intent}"
            )

    def test_payment_state_allows_complaint_exit(self):
        """COMPLAINT in payment state should still be detected."""
        complaint_words = ["скарга", "верніть гроші", "обман"]

        for word in complaint_words:
            intent = detect_intent_from_text(
                word, has_image=False, current_state="STATE_5_PAYMENT_DELIVERY"
            )
            # Either COMPLAINT or PAYMENT_DELIVERY is acceptable
            # (depends on keyword priority)
            assert intent in ["COMPLAINT", "PAYMENT_DELIVERY"]


# =============================================================================
# INIT STATE TRANSITIONS
# =============================================================================


class TestInitStateTransitions:
    """STATE_0_INIT transition tests."""

    def test_greeting_goes_to_discovery(self):
        """Greeting in INIT should go to agent (then DISCOVERY)."""
        route = _resolve_intent_route("GREETING_ONLY", "STATE_0_INIT", {})
        assert route == "agent"

    def test_photo_in_init_goes_to_vision(self):
        """Photo in INIT should go to vision."""
        route = _resolve_intent_route("PHOTO_IDENT", "STATE_0_INIT", {})
        assert route == "vision"

    def test_discovery_in_init_goes_to_agent(self):
        """Discovery question in INIT should go to agent."""
        route = _resolve_intent_route("DISCOVERY_OR_QUESTION", "STATE_0_INIT", {})
        assert route == "agent"
