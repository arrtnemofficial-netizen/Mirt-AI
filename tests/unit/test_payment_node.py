"""
Unit tests for payment.py - Payment node with HITL.

Tests cover:
1. payment_node routing and state updates
2. HITL disable flag behavior
3. Error handling
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.state_machine import State


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
            "selected_products": [
                {"name": "Костюм Лагуна", "price": 2190, "size": "122-128"}
            ],
            "step_number": 5,
        }

    @pytest.mark.asyncio
    async def test_hitl_disabled_skips_interrupt(self, base_state):
        """When ENABLE_PAYMENT_HITL=False, waits for delivery data (goto=end)."""
        from src.agents.langgraph.nodes.payment import payment_node
        
        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        
        mock_response = MagicMock()
        mock_response.reply_to_user = "Ось реквізити для оплати"
        
        with patch("src.agents.langgraph.nodes.payment.settings", mock_settings):
            with patch("src.agents.langgraph.nodes.payment.run_payment", new_callable=AsyncMock, return_value=mock_response):
                with patch("src.agents.langgraph.nodes.payment.log_agent_step"):
                    with patch("src.agents.langgraph.nodes.payment.track_metric"):
                        result = await payment_node(base_state)
        
        # Should wait for delivery data (end), not skip to upsell
        assert result.goto == "end"
        assert result.update["awaiting_human_approval"] is False
        assert result.update["dialog_phase"] == "WAITING_FOR_PAYMENT_PROOF"

    @pytest.mark.asyncio
    async def test_hitl_enabled_triggers_interrupt(self, base_state):
        """When ENABLE_PAYMENT_HITL=True, triggers interrupt."""
        from src.agents.langgraph.nodes.payment import payment_node
        from langgraph.types import interrupt
        
        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = True
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        
        mock_response = MagicMock()
        mock_response.reply_to_user = "Ось реквізити для оплати"
        
        # Mock interrupt to not actually pause
        with patch("src.agents.langgraph.nodes.payment.settings", mock_settings):
            with patch("src.agents.langgraph.nodes.payment.run_payment", new_callable=AsyncMock, return_value=mock_response):
                with patch("src.agents.langgraph.nodes.payment.interrupt", return_value=True) as mock_interrupt:
                    with patch("src.agents.langgraph.nodes.payment.log_agent_step"):
                        with patch("src.agents.langgraph.nodes.payment.track_metric"):
                            result = await payment_node(base_state)
        
        # Should call interrupt
        mock_interrupt.assert_called_once()
        # Should loop back to payment
        assert result.goto == "payment"
        assert result.update["awaiting_human_approval"] is True

    @pytest.mark.asyncio
    async def test_llm_failure_uses_fallback(self, base_state):
        """When LLM call fails, uses fallback response."""
        from src.agents.langgraph.nodes.payment import payment_node
        
        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        
        with patch("src.agents.langgraph.nodes.payment.settings", mock_settings):
            with patch("src.agents.langgraph.nodes.payment.run_payment", new_callable=AsyncMock, side_effect=Exception("API Error")):
                with patch("src.agents.langgraph.nodes.payment.log_agent_step"):
                    with patch("src.agents.langgraph.nodes.payment.track_metric"):
                        result = await payment_node(base_state)
        
        # Should still return valid Command with fallback message
        assert result.goto == "end"  # Wait for delivery data
        # Fallback message asks for delivery data
        assert "оформлення" in result.update["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_waiting_for_payment_proof_confirmation_without_image_does_not_crash(self, base_state):
        """In WAITING_FOR_PAYMENT_PROOF, 'Да' without image should not crash and should keep waiting."""
        from src.agents.langgraph.nodes.payment import payment_node

        state = {
            **base_state,
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
            "messages": [{"role": "user", "content": "Да"}],
            "metadata": {"session_id": "sess_123"},
        }

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        mock_settings.DEBUG_TRACE_LOGS = False

        mock_response = MagicMock()
        mock_response.reply_to_user = "Ок"  # should be overridden to ask for missing fields/screenshot
        mock_response.payment_details_sent = True
        mock_response.awaiting_payment_confirmation = True

        with patch("src.agents.langgraph.nodes.payment.settings", mock_settings):
            with patch(
                "src.agents.langgraph.nodes.payment.run_payment",
                new_callable=AsyncMock,
                return_value=mock_response,
            ):
                with patch("src.agents.langgraph.nodes.payment.log_agent_step"):
                    with patch("src.agents.langgraph.nodes.payment.track_metric"):
                        result = await payment_node(state)

        assert result.goto == "end"
        assert result.update["dialog_phase"] == "WAITING_FOR_PAYMENT_PROOF"
        # Should ask for either missing delivery data or screenshot
        content = result.update["messages"][0]["content"].lower()
        assert ("піб" in content) or ("скрін" in content) or ("квитанц" in content)

    @pytest.mark.asyncio
    async def test_waiting_for_payment_proof_with_image_and_full_data_goes_to_upsell(self, base_state):
        """When delivery data is complete and image proof is present, payment should complete the order."""
        from src.agents.langgraph.nodes.payment import payment_node

        state = {
            **base_state,
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
            "has_image": True,
            "messages": [{"role": "user", "content": ""}],
            "metadata": {
                "session_id": "sess_123",
                "customer_name": "Іван Петренко",
                "customer_phone": "0501234567",
                "customer_city": "Київ",
                "customer_nova_poshta": "54",
                "has_image": True,
            },
        }

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        mock_settings.DEBUG_TRACE_LOGS = False

        mock_response = MagicMock()
        mock_response.reply_to_user = "Дякую, бачу оплату"  # should pass through
        mock_response.payment_details_sent = True
        mock_response.awaiting_payment_confirmation = True

        async def _run_payment_side_effect(*args, **kwargs):
            deps = kwargs.get("deps")
            deps.customer_name = deps.customer_name or state["metadata"]["customer_name"]
            deps.customer_phone = deps.customer_phone or state["metadata"]["customer_phone"]
            deps.customer_city = deps.customer_city or state["metadata"]["customer_city"]
            deps.customer_nova_poshta = deps.customer_nova_poshta or state["metadata"]["customer_nova_poshta"]
            return mock_response

        with patch("src.agents.langgraph.nodes.payment.settings", mock_settings):
            with patch(
                "src.agents.langgraph.nodes.payment.run_payment",
                new_callable=AsyncMock,
                side_effect=_run_payment_side_effect,
            ):
                with patch("src.agents.langgraph.nodes.payment.log_agent_step"):
                    with patch("src.agents.langgraph.nodes.payment.track_metric"):
                        result = await payment_node(state)

        assert result.goto == "end"
        assert result.update["dialog_phase"] == "COMPLETED"


# =============================================================================
# State Update Tests
# =============================================================================


class TestPaymentStateUpdates:
    """Tests for payment state updates."""

    @pytest.mark.asyncio
    async def test_updates_current_state(self):
        """Payment node updates current_state to STATE_5."""
        from src.agents.langgraph.nodes.payment import payment_node
        
        state = {
            "session_id": "test",
            "current_state": State.STATE_4_OFFER.value,
            "dialog_phase": "OFFER_MADE",
            "messages": [],
            "metadata": {},
            "selected_products": [],
            "step_number": 1,
        }
        
        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        
        mock_response = MagicMock()
        mock_response.reply_to_user = "Test"
        
        with patch("src.agents.langgraph.nodes.payment.settings", mock_settings):
            with patch("src.agents.langgraph.nodes.payment.run_payment", new_callable=AsyncMock, return_value=mock_response):
                with patch("src.agents.langgraph.nodes.payment.log_agent_step"):
                    with patch("src.agents.langgraph.nodes.payment.track_metric"):
                        result = await payment_node(state)
        
        assert result.update["current_state"] == State.STATE_5_PAYMENT_DELIVERY.value

    @pytest.mark.asyncio
    async def test_increments_step_number(self):
        """Payment node increments step_number."""
        from src.agents.langgraph.nodes.payment import payment_node
        
        state = {
            "session_id": "test",
            "current_state": State.STATE_4_OFFER.value,
            "dialog_phase": "OFFER_MADE",
            "messages": [],
            "metadata": {},
            "selected_products": [],
            "step_number": 5,
        }
        
        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        
        mock_response = MagicMock()
        mock_response.reply_to_user = "Test"
        
        with patch("src.agents.langgraph.nodes.payment.settings", mock_settings):
            with patch("src.agents.langgraph.nodes.payment.run_payment", new_callable=AsyncMock, return_value=mock_response):
                with patch("src.agents.langgraph.nodes.payment.log_agent_step"):
                    with patch("src.agents.langgraph.nodes.payment.track_metric"):
                        result = await payment_node(state)
        
        assert result.update["step_number"] == 6
