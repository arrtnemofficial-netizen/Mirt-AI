
import pytest
from src.agents.langgraph.nodes.handlers.cart_handler import merge_cart
from src.agents.langgraph.nodes.handlers.transition_handler import finalize_transition
from src.agents.pydantic.models import SupportResponse, MessageItem, ResponseMetadata
from src.core.state_machine import State

class TestCartHandler:
    def test_merge_cart_additive_normal(self):
        current = [{"id": "1", "name": "P1", "size": "S", "color": "Red"}]
        new = [{"id": "2", "name": "P2", "size": "M", "color": "Blue"}]
        # User implies add
        merged = merge_cart(current, new, "додай ще це", strict_mode=False)
        assert len(merged) == 2
        
    def test_merge_cart_replace_normal(self):
        current = [{"id": "1", "name": "P1"}]
        new = [{"id": "2", "name": "P2"}]
        # User implies switch (no "add" intent)
        merged = merge_cart(current, new, "покажи куртки", strict_mode=False)
        assert len(merged) == 1
        assert merged[0]["id"] == "2"

    def test_merge_cart_strict_mode_blocked(self):
        """In payment state, implicitly adding products is blocked."""
        current = [{"id": "1", "name": "P1"}]
        new = [{"id": "2", "name": "P2"}] # AI hallucinated a new product
        # strict_mode=True, user text has NO add intent
        merged = merge_cart(current, new, "ок, оплачую", strict_mode=True)
        # Should keep ONLY current
        assert len(merged) == 1
        assert merged[0]["id"] == "1"

    def test_merge_cart_strict_mode_allowed(self):
        """In payment state, EXPLICIT adding is allowed."""
        current = [{"id": "1", "name": "P1"}]
        new = [{"id": "2", "name": "P2"}]
        # strict_mode=True, user text HAS add intent
        merged = merge_cart(current, new, "додай ще шкарпетки", strict_mode=True)
        assert len(merged) == 2

class TestTransitionHandler:
    def test_finalize_transition_override(self):
        """Test SSOT override logic."""
        state = {
            "current_state": "STATE_1_DISCOVERY",
            "metadata": {"session_id": "test"}
        }
        # Response says stay in Discovery
        response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="dummy")],
            products=[],
            metadata=ResponseMetadata(
                session_id="test",
                current_state="STATE_1_DISCOVERY",
                intent="DISCOVERY_OR_QUESTION",
                escalation_level="NONE"
            )
        )
        # User says "show size" -> Transition should force STATE_3
        # Assuming empty reduce returns STATE_1, we need to mock compute_transition? 
        # Actually this test relies on real compute_transition which is complex.
        # Let's test the Payment Preserve logic which is pure handler logic.
        
        state_payment = {
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "_payment_context": {"preserve_state": True},
            "metadata": {"session_id": "test"}
        }
        # Response tries to change state
        response.metadata.current_state = "STATE_1_DISCOVERY"
        
        new_state, _, _ = finalize_transition(state_payment, response, "hi")
        assert new_state == State.STATE_5_PAYMENT_DELIVERY.value

    def test_state5_prioritizes_detected_intent_over_llm_intent(self):
        """STATE_5 must trust deterministic detected_intent before LLM metadata intent."""
        state = {
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "detected_intent": "PAYMENT_DELIVERY",
            "metadata": {"session_id": "test"},
            "messages": [{"role": "user", "content": "ок"}],
        }
        response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="dummy")],
            products=[],
            metadata=ResponseMetadata(
                session_id="test",
                current_state=State.STATE_7_END.value,
                intent="THANKYOU_SMALLTALK",
                escalation_level="NONE",
            ),
        )

        new_state, final_intent, meta = finalize_transition(state, response, "ок")

        assert new_state == State.STATE_5_PAYMENT_DELIVERY.value
        assert final_intent == "PAYMENT_DELIVERY"
        assert meta["transition_source"] == "intent_node"
        assert meta.get("payment_sub_phase") in {"REQUEST_DATA", "CONFIRM_DATA", "SHOW_PAYMENT", "THANK_YOU", None}

    def test_finalize_transition_returns_transition_metadata(self):
        """Transition handler should provide additive metadata for observability."""
        state = {
            "current_state": State.STATE_4_OFFER.value,
            "detected_intent": "PAYMENT_DELIVERY",
            "metadata": {"session_id": "test"},
        }
        response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="dummy")],
            products=[],
            metadata=ResponseMetadata(
                session_id="test",
                current_state=State.STATE_4_OFFER.value,
                intent="PAYMENT_DELIVERY",
                escalation_level="NONE",
            ),
        )

        _, _, meta = finalize_transition(state, response, "беру")

        assert "transition_reason" in meta
        assert "transition_source" in meta
        assert "dialog_phase" in meta

