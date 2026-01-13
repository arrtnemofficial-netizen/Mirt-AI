"""
E2E Payment Flow Test (V2).
===========================
Verifies the Critical Path: Payment Proof Processing.
Focuses on SSOT architecture: Router -> Payment Node -> State Update.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from src.agents import create_initial_state
from src.core.state_machine import State, Intent
from src.agents.langgraph.edges import master_router
from src.agents.langgraph.nodes.payment import payment_node

@pytest.mark.asyncio
class TestPaymentFlowV2:
    """End-to-end tests for payment processing."""

    async def test_receipt_image_routes_to_payment(self):
        """
        Scenario: User sends a receipt image in ANY state (or specifically Payment state).
        Expected: Router detects 'transactional' purpose -> routes to 'payment'.
        """
        # 1. Setup State
        state = create_initial_state(
            session_id="test_pay_1",
            messages=[
                {"role": "assistant", "content": "Будь ласка, надішліть скріншот оплати."},
                {"role": "user", "content": "", "image_url": "https://bank.com/receipt.jpg"}
            ],
            metadata={
                "current_state": "STATE_5_PAYMENT_DELIVERY",
                "payment_request_data_sent": True,
                "has_image": True
            }
        )
        state["current_state"] = "STATE_5_PAYMENT_DELIVERY" # Set top-level state
        state["has_image"] = True # Top-level flag

        # 2. Mock Photo Purpose (Critical: This drives the router)
        with patch("src.agents.langgraph.rules.photo_purpose.determine_photo_purpose") as mock_purpose:
            mock_purpose.return_value = ("transactional", "looks like a receipt")

            # 3. Test Router
            next_node = master_router(state)

            assert next_node == "payment", \
                f"Receipt image should route to 'payment', got '{next_node}'"

    async def test_payment_node_processes_receipt(self):
        """
        Scenario: Payment node receives a receipt.
        Expected:
        1. Detects proof (via rule).
        2. Persists order.
        3. Updates state/phase to END/COMPLETED (or UPSELL).
        """
        # 1. Setup State
        state = create_initial_state(
            session_id="test_pay_2",
            messages=[
                {"role": "user", "content": "Ось чек", "image_url": "http://img.jpg"}
            ],
            metadata={
                "current_state": "STATE_5_PAYMENT_DELIVERY",
                "payment_sub_phase": "SHOW_PAYMENT",
                "has_image": True
            }
        )
        state["current_state"] = "STATE_5_PAYMENT_DELIVERY" # Set top-level state
        # Mock products for order persistence
        state["selected_products"] = [{"name": "Test Product", "price": 100}]

        # 2. Mock Dependencies
        # A. Mock Proof Detection (Rule)
        with patch("src.agents.langgraph.rules.payment_proof.detect_payment_proof", return_value=True):
            # Also mock product addition detection to ensure we don't skip proof check
            with patch("src.agents.langgraph.rules.product_addition.detect_product_addition_intent", return_value=False):
                # Also need to mock get_payment_sub_phase because payment_node -> handle_delivery_data logic depends on it
                # The router logic: if payment_sub_phase == "SHOW_PAYMENT", call handle_delivery_data
                # But compute_transition inside payment_node calculates sub_phase.
                with patch("src.agents.langgraph.state_prompts.get_payment_sub_phase", return_value="SHOW_PAYMENT"):

                    # B. Mock CRM Persistence (avoid DB)
                    with patch("src.agents.langgraph.nodes.helpers.payment.delivery.persist_order_and_queue_crm", new_callable=AsyncMock) as mock_persist:
                        mock_persist.return_value = "order_123"

                        # C. Mock Notifications
                        with patch("src.services.notifications.NotificationService.send_escalation_alert", new_callable=AsyncMock):

                            # D. Mock Snippet Loader (to avoid file system reads)
                            with patch("src.agents.langgraph.nodes.helpers.vision.snippet_loader.get_snippet_by_header", return_value=["Дякуємо!"]):

                                # 3. Run Node
                                result = await payment_node(state)

                                # 4. Verify Result
                                # Should go to END (or UPSELL)
                                assert result.goto in ("end", "upsell")

                                # Should mark proof as received in metadata
                                assert result.update["metadata"].get("payment_proof_received") is True, \
                                    "Metadata should mark proof as received"

                                # Should have persisted order
                                mock_persist.assert_called_once()

    async def test_text_confirmation_without_image(self):
        """
        Scenario: User says 'I paid' but no image.
        Expected: Router -> Payment (to handle logic) -> Payment Node checks proof -> Missing -> Ask again.
        """
        state = create_initial_state(
            session_id="test_pay_3",
            messages=[{"role": "user", "content": "Я вже оплатила"}],
            metadata={
                "current_state": "STATE_5_PAYMENT_DELIVERY",
                "payment_request_data_sent": True,
                "payment_sub_phase": "SHOW_PAYMENT" # CRITICAL for SSOT to calc WAITING_FOR_PAYMENT_PROOF
            }
        )
        state["current_state"] = "STATE_5_PAYMENT_DELIVERY" # Set top-level state

        # Intent detection
        with patch("src.agents.langgraph.nodes.intent.detect_intent_from_text", return_value="PAYMENT_DELIVERY"):
            # Mock get_payment_sub_phase to ensure SSOT reducer calculates WAITING_FOR_PAYMENT_PROOF
            with patch("src.agents.langgraph.state_prompts.get_payment_sub_phase", return_value="SHOW_PAYMENT"):

                # For STATE_5 + WAITING_FOR_PAYMENT_PROOF, master_router -> "payment"
                next_node = master_router(state)
                assert next_node == "payment", f"Should route to payment node, got {next_node}"
