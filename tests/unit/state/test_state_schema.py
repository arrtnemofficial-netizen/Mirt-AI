"""
CONTRACT: ConversationState schema validation.

Ensures the LangGraph state structure doesn't break.
All nodes depend on this contract.
"""

import pytest


@pytest.mark.contract
@pytest.mark.critical
class TestConversationStateContract:
    """Verify ConversationState TypedDict contract."""

    def test_state_has_core_fields(self):
        """ConversationState must have core conversation fields."""
        from src.agents.langgraph.state import ConversationState

        # TypedDict annotations
        annotations = ConversationState.__annotations__

        core_fields = [
            "messages",
            "current_state",
            "metadata",
            "session_id",
            "detected_intent",
        ]

        for field in core_fields:
            assert field in annotations, f"CONTRACT: ConversationState missing core field '{field}'"

    def test_state_has_dialog_phase(self):
        """ConversationState must have dialog_phase for sub-state tracking."""
        from src.agents.langgraph.state import ConversationState

        annotations = ConversationState.__annotations__
        assert "dialog_phase" in annotations, "CONTRACT: ConversationState must have 'dialog_phase'"

    def test_state_has_product_fields(self):
        """ConversationState must have product tracking fields."""
        from src.agents.langgraph.state import ConversationState

        annotations = ConversationState.__annotations__

        # Use actual field names from the state
        product_fields = ["selected_products", "offered_products"]
        for field in product_fields:
            assert field in annotations, (
                f"CONTRACT: ConversationState missing product field '{field}'"
            )

    def test_state_has_moderation_fields(self):
        """ConversationState must have moderation fields."""
        from src.agents.langgraph.state import ConversationState

        annotations = ConversationState.__annotations__
        # Use actual field name
        assert "should_escalate" in annotations, (
            "CONTRACT: ConversationState must have 'should_escalate'"
        )

    def test_state_has_payment_fields(self):
        """ConversationState must have payment flow fields."""
        from src.agents.langgraph.state import ConversationState

        annotations = ConversationState.__annotations__

        # Use actual field names
        payment_fields = ["awaiting_human_approval", "human_approved"]
        for field in payment_fields:
            assert field in annotations, (
                f"CONTRACT: ConversationState missing payment field '{field}'"
            )

    def test_state_has_memory_fields(self):
        """ConversationState must have memory system fields."""
        from src.agents.langgraph.state import ConversationState

        annotations = ConversationState.__annotations__

        # Use actual field names
        memory_fields = ["memory_profile", "memory_facts", "memory_context_prompt"]
        for field in memory_fields:
            assert field in annotations, (
                f"CONTRACT: ConversationState missing memory field '{field}'"
            )


@pytest.mark.contract
@pytest.mark.critical
class TestStateEnumContract:
    """Verify State and Intent enum contracts."""

    def test_state_enum_values_stable(self):
        """State enum values must be stable strings."""
        from src.core.state_machine import State

        # These exact values are used in DB, logs, and external systems
        expected_values = {
            "STATE_0_INIT": "STATE_0_INIT",
            "STATE_1_DISCOVERY": "STATE_1_DISCOVERY",
            "STATE_2_VISION": "STATE_2_VISION",
            "STATE_3_SIZE_COLOR": "STATE_3_SIZE_COLOR",
            "STATE_4_OFFER": "STATE_4_OFFER",
            "STATE_5_PAYMENT_DELIVERY": "STATE_5_PAYMENT_DELIVERY",
            "STATE_6_UPSELL": "STATE_6_UPSELL",
            "STATE_7_END": "STATE_7_END",
        }

        for name, value in expected_values.items():
            state = getattr(State, name)
            assert state.value == value, (
                f"CONTRACT: State.{name} value changed from '{value}' to '{state.value}'"
            )

    def test_intent_enum_values_stable(self):
        """Intent enum values must be stable strings."""
        from src.core.state_machine import Intent

        # These exact values are used in routing and logging
        expected_intents = [
            "PHOTO_IDENT",
            "PAYMENT_DELIVERY",
            "COMPLAINT",
            "SIZE_HELP",
            "COLOR_HELP",
            "DISCOVERY_OR_QUESTION",
            "GREETING_ONLY",
            "THANKYOU_SMALLTALK",
        ]

        for intent_name in expected_intents:
            assert hasattr(Intent, intent_name), f"CONTRACT: Intent.{intent_name} was removed"


@pytest.mark.contract
class TestDialogPhaseContract:
    """Verify dialog_phase string values are stable."""

    def test_offer_phase_values(self):
        """Offer-related dialog phases must be stable."""
        # These are used in routing logic
        expected_phases = [
            "OFFER_MADE",
            "WAITING_FOR_SIZE",
            "WAITING_FOR_COLOR",
        ]

        # Just verify they're valid strings that routing expects
        from src.agents.langgraph.edges import master_router

        for phase in expected_phases:
            state = {
                "current_state": "STATE_4_OFFER",
                "detected_intent": None,
                "has_image": False,
                "is_escalated": False,
                "dialog_phase": phase,
                "metadata": {},
            }
            # Should not raise
            route = master_router(state)
            assert isinstance(route, str)

    def test_payment_phase_values(self):
        """Payment-related dialog phases must be stable."""
        expected_phases = [
            "WAITING_FOR_PAYMENT_METHOD",
            "WAITING_FOR_PAYMENT_PROOF",
        ]

        from src.agents.langgraph.edges import master_router

        for phase in expected_phases:
            state = {
                "current_state": "STATE_5_PAYMENT_DELIVERY",
                "detected_intent": "PAYMENT_DELIVERY",
                "has_image": False,
                "is_escalated": False,
                "dialog_phase": phase,
                "metadata": {},
            }
            route = master_router(state)
            assert route == "payment", f"CONTRACT: {phase} must route to 'payment'"
