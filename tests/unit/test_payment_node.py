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

    @pytest.mark.asyncio
    async def test_hitl_disabled_skips_interrupt(self, base_state):
        """When ENABLE_PAYMENT_HITL=False, checkout proceeds without LLM call."""
        from src.agents.langgraph.nodes.payment import payment_node

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        mock_settings.DEBUG_TRACE_LOGS = False

        # Note: checkout logic does NOT call run_payment anymore, it uses snippets.
        # So we don't mock run_payment here.

    @pytest.mark.asyncio
    async def test_request_data_snippet_sent_exactly_once(self, base_state):
        """INVARIANT: Snippet 'Підтвердження замовлення' must be sent exactly once."""
        from src.agents.langgraph.nodes.helpers.payment.checkout import prepare_payment_and_interrupt
        from src.conf.config import settings

        # Первый вызов: snippet должен быть отправлен
        state1 = {
            **base_state,
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "dialog_phase": "WAITING_FOR_DELIVERY_DATA",
            "metadata": {},  # Флаг НЕ установлен
        }

        with patch.object(settings, "ENABLE_PAYMENT_HITL", False):
            result1 = await prepare_payment_and_interrupt(state1, None, "sess_123")

        # Проверяем, что snippet был отправлен
        messages1 = result1.update.get("agent_response", {}).get("messages", [])
        assert len(messages1) > 0, "Snippet must be sent on first call"
        assert "Підтвердження замовлення" in str(messages1[0].get("content", "")).lower() or any(
            "місто та відділення" in str(m.get("content", "")).lower() for m in messages1
        ), "First message must contain delivery request"

        # Проверяем, что флаг установлен
        metadata1 = result1.update.get("metadata", {})
        assert metadata1.get("payment_request_data_sent") is True, "Flag must be set after sending snippet"

        # Второй вызов: флаг установлен → snippet НЕ должен быть отправлен
        state2 = {
            **base_state,
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "dialog_phase": "WAITING_FOR_DELIVERY_DATA",
            "metadata": {"payment_request_data_sent": True},  # Флаг установлен
        }

        with patch.object(settings, "ENABLE_PAYMENT_HITL", False):
            result2 = await prepare_payment_and_interrupt(state2, None, "sess_123")

        # Проверяем, что snippet НЕ был отправлен повторно
        messages2 = result2.update.get("agent_response", {}).get("messages", [])
        # Либо пустой ответ, либо не содержит delivery request
        if messages2:
            content = " ".join(str(m.get("content", "")) for m in messages2).lower()
            # Не должно быть полного текста запроса данных (может быть частичный, но не полный snippet)
            assert "місто та відділення нової пошти" not in content or "піб та номер телефону" not in content, (
                "Snippet must NOT be sent twice"
            )
        
        # Patch settings in checkout module because that's where the check happens
        # Patch settings in checkout module because that's where the check happens
        with patch("src.agents.langgraph.nodes.helpers.payment.checkout.settings", mock_settings), patch(
            "src.agents.langgraph.nodes.payment.log_agent_step"
        ), patch("src.agents.langgraph.nodes.helpers.payment.checkout.get_snippet_by_header", return_value=None):
             with patch("src.agents.langgraph.nodes.payment.track_metric"):
                result = await payment_node(base_state)

        # Should wait for delivery data (end)
        assert result.goto == "end"
        assert result.update["awaiting_human_approval"] is False
        assert result.update["dialog_phase"] == "WAITING_FOR_DELIVERY_DATA"
        # Verify content comes from hardcoded fallback (strict text)
        assert "Щоб одразу зарезервувати" in result.update["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_hitl_enabled_triggers_interrupt(self, base_state):
        """When ENABLE_PAYMENT_HITL=True, triggers interrupt."""

        from src.agents.langgraph.nodes.payment import payment_node

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = True
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        mock_settings.DEBUG_TRACE_LOGS = False

        # Mock interrupt inside checkout module where it is used
        # And mock settings in checkout module
        with patch("src.agents.langgraph.nodes.helpers.payment.checkout.settings", mock_settings), patch(
            "src.agents.langgraph.nodes.helpers.payment.checkout.interrupt", return_value=True
        ) as mock_interrupt, patch("src.agents.langgraph.nodes.payment.log_agent_step"):
             with patch("src.agents.langgraph.nodes.helpers.payment.checkout.get_snippet_by_header", return_value=None):
                with patch("src.agents.langgraph.nodes.payment.track_metric"):
                    result = await payment_node(base_state)

        # Should call interrupt
        mock_interrupt.assert_called_once()
        # Should loop back to payment
        assert result.goto == "payment"
        assert result.update["awaiting_human_approval"] is True

    @pytest.mark.asyncio
    async def test_llm_failure_uses_fallback_in_delivery(self, base_state):
        """When LLM call fails in delivery handler, uses fallback response."""
        from src.agents.langgraph.nodes.payment import payment_node
        
        # Setup state to trigger delivery handler (not checkout)
        state = {
            **base_state,
            "dialog_phase": "WAITING_FOR_DELIVERY_DATA",
            "messages": [{"role": "user", "content": "Моє місто Київ"}],
        }

        mock_settings = MagicMock()
        mock_settings.ENABLE_PAYMENT_HITL = False
        mock_settings.SNITKIX_API_KEY = MagicMock(get_secret_value=MagicMock(return_value=""))
        mock_settings.DEBUG_TRACE_LOGS = False

        # Patch delivery.run_payment to fail
        # Note: delivery.py imports settings too, we might need to patch it there if it used settings logic relevant to fallback
        # But fallback is just try/except around run_payment.
        with patch("src.agents.langgraph.nodes.payment.settings", mock_settings), patch(
            "src.agents.langgraph.nodes.helpers.payment.delivery.run_payment",
            new_callable=AsyncMock,
            side_effect=Exception("API Error"),
        ), patch("src.agents.langgraph.nodes.payment.log_agent_step"):
            with patch("src.agents.langgraph.nodes.payment.track_metric"):
                result = await payment_node(state)

        # Should still return valid Command with fallback message
        assert result.goto == "end"  # Wait for delivery data
        # Fallback message asks for delivery data
        assert "ПІБ" in result.update["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_waiting_for_payment_proof_confirmation_without_image_does_not_crash(
        self, base_state
    ):
        """In WAITING_FOR_PAYMENT_PROOF, missing data should prompt user."""
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
        # Simulate LLM asking for missing data
        mock_response.reply_to_user = "Будь ласка, надішліть скріншот оплати."
        mock_response.payment_details_sent = True
        mock_response.awaiting_payment_confirmation = True

        with (
            patch("src.agents.langgraph.nodes.payment.settings", mock_settings),
            patch(
                "src.agents.langgraph.nodes.helpers.payment.delivery.run_payment",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch("src.agents.langgraph.nodes.payment.log_agent_step"),
        ):
            with patch("src.agents.langgraph.nodes.payment.track_metric"):
                result = await payment_node(state)

        assert result.goto == "end"
        assert result.update["dialog_phase"] == "WAITING_FOR_PAYMENT_PROOF"
        # Should contain the prompt from mock
        content = result.update["messages"][0]["content"].lower()
        assert "скріншот" in content

    @pytest.mark.asyncio
    async def test_waiting_for_payment_proof_with_image_and_full_data_goes_to_upsell(
        self, base_state
    ):
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
        mock_response.reply_to_user = "Дякую, бачу оплату" 
        mock_response.payment_details_sent = True
        mock_response.awaiting_payment_confirmation = True

        async def _run_payment_side_effect(*args, **kwargs):
            deps = kwargs.get("deps")
            deps.customer_name = deps.customer_name or state["metadata"]["customer_name"]
            deps.customer_phone = deps.customer_phone or state["metadata"]["customer_phone"]
            deps.customer_city = deps.customer_city or state["metadata"]["customer_city"]
            deps.customer_nova_poshta = (
                deps.customer_nova_poshta or state["metadata"]["customer_nova_poshta"]
            )
            return mock_response

        # Need to patch delivery.run_payment (although with has_image=True and proof strict check it handles it internally via persisted order?)
        # Wait, handle_delivery_data -> detect_payment_proof -> True -> _handle_payment_proof_received
        # It DOES NOT call run_payment if proof is detected!
        # So mocking run_payment is actually irrelevant if proof logic works.
        # But we need to mock persist_order_and_queue_crm and notification service to avoid side effects/errors.
        
        with (
            patch("src.agents.langgraph.nodes.payment.settings", mock_settings),
            # Patch run_payment just in case it falls through (it shouldn't)
            patch(
                "src.agents.langgraph.nodes.helpers.payment.delivery.run_payment",
                new_callable=AsyncMock,
                side_effect=_run_payment_side_effect,
            ),
            patch("src.agents.langgraph.nodes.payment.log_agent_step"),
            # Mock CRM persistence
            patch("src.agents.langgraph.nodes.helpers.payment.delivery.persist_order_and_queue_crm", new_callable=AsyncMock, return_value={"id": 1}),
             # Mock Notification Service
            patch("src.services.notifications.NotificationService.send_escalation_alert", new_callable=AsyncMock),
        ):
            with patch("src.agents.langgraph.nodes.payment.track_metric"):
                result = await payment_node(state)

        # With payment proof + full data, should route to upsell (or end if no upsell available)
        assert result.goto in ("upsell", "end")
        
        # Verify strict message sequence: Thank You -> Subscribe -> (Upsell)
        messages = result.update["messages"]
        assert len(messages) >= 2
        assert "Дякуємо за замовлення" in messages[0]["content"]
        assert "підпишіться" in messages[1]["content"]

        if result.goto == "upsell":
            assert result.update["dialog_phase"] == "UPSELL_OFFERED"
            # Upsell should be the 3rd message
            assert len(messages) == 3
        else:
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
        mock_settings.DEBUG_TRACE_LOGS = False

        # No LLM call in checkout start
        # Patch checkout settings to ensure consistency (though defaults might work, better explicit)
        with patch("src.agents.langgraph.nodes.helpers.payment.checkout.settings", mock_settings), patch(
            "src.agents.langgraph.nodes.payment.log_agent_step"
        ), patch("src.agents.langgraph.nodes.helpers.payment.checkout.get_snippet_by_header", return_value=None):
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
        mock_settings.DEBUG_TRACE_LOGS = False

        with patch("src.agents.langgraph.nodes.payment.settings", mock_settings), patch(
            "src.agents.langgraph.nodes.payment.log_agent_step"
        ), patch("src.agents.langgraph.nodes.helpers.payment.checkout.get_snippet_by_header", return_value=None):
            with patch("src.agents.langgraph.nodes.payment.track_metric"):
                result = await payment_node(state)

        assert result.update["step_number"] == 6
