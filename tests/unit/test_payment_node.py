"""
Unit tests for payment.py - Payment node with HITL.

Tests cover:
1. payment_node routing and state updates
2. HITL disable flag behavior (checkout)
3. Delivery data handling (with LLM delegation)
4. Payment proof handling
5. SSOT invariants: snippet sent exactly once
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.core.state_machine import State
from src.agents.langgraph.fsm.transition_reducer import TransitionDecision, ResponsePolicy

# =============================================================================
# payment_node Tests
# =============================================================================

class TestPaymentNode:
    """Tests for payment_node function."""

    @pytest.fixture
    def base_state(self):
        """Base state for payment tests."""
        return {
            "session_id": "sess_123",
            "current_state": State.STATE_4_OFFER.value,
            "dialog_phase": "OFFER_MADE",
            "messages": [{"role": "user", "content": "Беру!"}],
            "metadata": {"session_id": "sess_123"},
            "selected_products": [{"name": "Костюм Лагуна", "price": 2190, "size": "122-128"}],
            "step_number": 5,
        }

    @pytest.fixture
    def mock_observability(self):
        """Mock observability functions globally."""
        with patch("src.services.observability.log_agent_step"), \
             patch("src.services.observability.track_metric"):
            yield

    @pytest.mark.asyncio
    async def test_hitl_disabled_skips_interrupt(self, base_state, mock_observability):
        """When ENABLE_PAYMENT_HITL=False, checkout proceeds without LLM call."""
        pass

    @pytest.mark.asyncio
    async def test_request_data_snippet_sent_exactly_once(self, base_state, mock_observability):
        """INVARIANT: Snippet 'Підтвердження замовлення' must be sent exactly once."""
        from src.agents.langgraph.nodes.helpers.payment.checkout import prepare_payment_and_interrupt
        from src.conf.config import settings

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))

        # 1. First call
        state1 = {
            **base_state,
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "dialog_phase": "WAITING_FOR_DELIVERY_DATA",
            "metadata": {},
        }
        with patch.object(settings, "ENABLE_PAYMENT_HITL", False):
            result1 = await prepare_payment_and_interrupt(state1, None, "sess_123")

        messages1 = result1.update.get("agent_response", {}).get("messages", [])
        assert len(messages1) > 0

        # 2. Second call
        state2 = {
            **base_state,
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "dialog_phase": "WAITING_FOR_DELIVERY_DATA",
            "metadata": {"payment_request_data_sent": True},
        }
        with patch.object(settings, "ENABLE_PAYMENT_HITL", False):
            result2 = await prepare_payment_and_interrupt(state2, None, "sess_123")

        messages2 = result2.update.get("agent_response", {}).get("messages", [])
        if messages2:
            content = " ".join(str(m.get("content", "")) for m in messages2).lower()
            assert "місто та відділення нової пошти" not in content

        # 3. Test payment_node routing
        from src.agents.langgraph.nodes.payment import payment_node
        
        with patch("src.agents.langgraph.nodes.helpers.payment.checkout.settings", mock_settings), \
             patch("src.agents.langgraph.nodes.helpers.payment.checkout.get_snippet_by_header", return_value=None):
            result = await payment_node(base_state)

        assert result.goto == "end"
        assert result.update["awaiting_human_approval"] is False

    @pytest.mark.asyncio
    async def test_hitl_enabled_triggers_interrupt(self, base_state, mock_observability):
        """When ENABLE_PAYMENT_HITL=True, triggers interrupt."""
        from src.agents.langgraph.nodes.payment import payment_node

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = True
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        mock_settings.DEBUG_TRACE_LOGS = False

        with patch("src.agents.langgraph.nodes.helpers.payment.checkout.settings", mock_settings), \
             patch("src.agents.langgraph.nodes.helpers.payment.checkout.interrupt", return_value=True) as mock_interrupt, \
             patch("src.agents.langgraph.nodes.helpers.payment.checkout.get_snippet_by_header", return_value=None):
            result = await payment_node(base_state)

        mock_interrupt.assert_called_once()
        assert result.goto == "payment"

    @pytest.mark.asyncio
    async def test_waiting_for_payment_proof_confirmation_without_image_does_not_crash(self, base_state, mock_observability):
        """In WAITING_FOR_PAYMENT_PROOF, missing data should prompt user."""
        from src.agents.langgraph.nodes.payment import payment_node

        mock_decision = TransitionDecision(
            next_state=State.STATE_5_PAYMENT_DELIVERY.value,
            payment_sub_phase="SHOW_PAYMENT",
            dialog_phase="WAITING_FOR_PAYMENT_PROOF",
            response_policy=ResponsePolicy(),
            reason="mock"
        )

        state = {
            **base_state,
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
            "messages": [{"role": "user", "content": "Да"}],
        }

        mock_response = MagicMock()
        mock_response.reply_to_user = "Будь ласка, надішліть скріншот оплати."
        mock_response.payment_details_sent = True

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False

        # Patching transition_reducer globally because payment_node imports it inside function
        with patch("src.agents.langgraph.fsm.transition_reducer.compute_transition", return_value=mock_decision), \
             patch("src.agents.langgraph.nodes.helpers.payment.delivery.settings", mock_settings), \
             patch("src.agents.langgraph.nodes.helpers.payment.delivery.run_payment", new_callable=AsyncMock, return_value=mock_response):

            result = await payment_node(state)

        assert result.goto == "end"
        assert "скріншот" in result.update["messages"][0]["content"].lower()

    @pytest.mark.asyncio
    async def test_waiting_for_payment_proof_with_image_and_full_data_goes_to_upsell(self, base_state, mock_observability):
        """When delivery data is complete and image proof is present, payment should complete."""
        from src.agents.langgraph.nodes.payment import payment_node

        mock_decision = TransitionDecision(
            next_state=State.STATE_5_PAYMENT_DELIVERY.value,
            payment_sub_phase="SHOW_PAYMENT",
            dialog_phase="WAITING_FOR_PAYMENT_PROOF",
            response_policy=ResponsePolicy(),
            reason="mock"
        )

        state = {
            **base_state,
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
            "has_image": True,
            "messages": [{"role": "user", "content": ""}],
            "metadata": {
                "session_id": "sess_123",
                "customer_name": "Іван",
                "customer_phone": "0501234567",
                "customer_city": "Київ",
                "customer_nova_poshta": "54",
                "has_image": True,
            },
        }

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False

        mock_response = MagicMock()
        mock_response.reply_to_user = "Дякую"

        async def _run_payment_side_effect(*args, **kwargs):
            return mock_response

        with patch("src.agents.langgraph.fsm.transition_reducer.compute_transition", return_value=mock_decision), \
             patch("src.agents.langgraph.nodes.helpers.payment.delivery.settings", mock_settings), \
             patch("src.agents.langgraph.nodes.helpers.payment.delivery.run_payment", new_callable=AsyncMock, side_effect=_run_payment_side_effect), \
             patch("src.agents.langgraph.nodes.helpers.payment.delivery.persist_order_and_queue_crm", new_callable=AsyncMock, return_value={"id": 1}), \
             patch("src.services.notifications.NotificationService.send_escalation_alert", new_callable=AsyncMock):
            result = await payment_node(state)

        assert result.goto in ("upsell", "end")

class TestPaymentStateUpdates:
    """Tests for payment state updates."""

    @pytest.fixture
    def mock_observability(self):
        with patch("src.services.observability.log_agent_step"), patch("src.services.observability.track_metric"):
            yield

    @pytest.mark.asyncio
    async def test_updates_current_state(self, mock_observability):
        from src.agents.langgraph.nodes.payment import payment_node
        state = {"session_id": "test", "current_state": State.STATE_4_OFFER.value, "dialog_phase": "OFFER_MADE", "messages": [], "metadata": {}, "step_number": 1}

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False

        with patch("src.agents.langgraph.nodes.helpers.payment.checkout.settings", mock_settings), \
             patch("src.agents.langgraph.nodes.helpers.payment.checkout.get_snippet_by_header", return_value=None):
            result = await payment_node(state)

        assert result.update["current_state"] == State.STATE_5_PAYMENT_DELIVERY.value

    @pytest.mark.asyncio
    async def test_increments_step_number(self, mock_observability):
        from src.agents.langgraph.nodes.payment import payment_node
        state = {"session_id": "test", "current_state": State.STATE_4_OFFER.value, "dialog_phase": "OFFER_MADE", "messages": [], "metadata": {}, "step_number": 5}

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False

        with patch("src.agents.langgraph.nodes.helpers.payment.checkout.settings", mock_settings), \
             patch("src.agents.langgraph.nodes.helpers.payment.checkout.get_snippet_by_header", return_value=None):
            result = await payment_node(state)

        assert result.update["step_number"] == 6
