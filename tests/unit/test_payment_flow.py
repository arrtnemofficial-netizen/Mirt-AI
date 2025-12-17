"""
Unit tests for payment_flow.py - Pure FSM functions for payment sub-phases.

Tests cover:
1. CustomerData dataclass
2. handle_request_data - when data incomplete vs complete
3. handle_confirm_data - full payment vs prepay vs unknown
4. handle_show_payment - confirmation vs still waiting
5. process_payment_subphase - dispatcher
"""

import pytest


pytest.importorskip(
    "src.agents.langgraph.nodes.payment_flow",
    reason="payment_flow module was removed after consolidating payment logic into payment.py + payment_agent.py",
)


from src.agents.langgraph.nodes.payment_flow import (  # noqa: E402
    CustomerData,
    PaymentFlowResult,
    FULL_PAYMENT_KEYWORDS,
    PREPAY_KEYWORDS,
    PAYMENT_CONFIRM_KEYWORDS,
    handle_request_data,
    handle_confirm_data,
    handle_show_payment,
    process_payment_subphase,
    extract_customer_data_from_state,
    get_product_info_from_state,
)
from src.core.state_machine import State  # noqa: E402


# =============================================================================
# CustomerData Tests
# =============================================================================


class TestCustomerData:
    """Tests for CustomerData dataclass."""

    def test_incomplete_data_missing_all(self):
        """Empty CustomerData is not complete."""
        data = CustomerData()
        assert data.is_complete is False

    def test_incomplete_data_missing_phone(self):
        """Missing phone makes data incomplete."""
        data = CustomerData(name="Іван", city="Київ", nova_poshta="54")
        assert data.is_complete is False

    def test_incomplete_data_missing_nova_poshta(self):
        """Missing nova_poshta makes data incomplete."""
        data = CustomerData(name="Іван", phone="0501234567", city="Київ")
        assert data.is_complete is False

    def test_complete_data(self):
        """All fields filled = complete."""
        data = CustomerData(
            name="Іван Петренко",
            phone="0501234567",
            city="Київ",
            nova_poshta="54"
        )
        assert data.is_complete is True


# =============================================================================
# handle_request_data Tests
# =============================================================================


class TestHandleRequestData:
    """Tests for REQUEST_DATA sub-phase."""

    def test_incomplete_data_asks_for_more(self):
        """When data incomplete, asks user to provide it."""
        data = CustomerData(name="Іван")
        result = handle_request_data(data, "session_123")
        
        assert result.next_sub_phase == "REQUEST_DATA"
        assert result.next_state == State.STATE_5_PAYMENT_DELIVERY.value
        assert "ПІБ" in result.messages[0].content
        assert result.event == "simple_answer"

    def test_complete_data_transitions_to_confirm(self):
        """When all data collected, transition to CONFIRM_DATA."""
        data = CustomerData(
            name="Іван Петренко",
            phone="0501234567",
            city="Київ",
            nova_poshta="54"
        )
        result = handle_request_data(data, "session_123")
        
        assert result.next_sub_phase == "CONFIRM_DATA"
        assert result.next_state == State.STATE_5_PAYMENT_DELIVERY.value
        assert result.event == "simple_answer"
        
        # Should show summary
        messages_text = " ".join(m.content for m in result.messages)
        assert "Іван Петренко" in messages_text
        assert "0501234567" in messages_text
        assert "Київ" in messages_text
        assert "54" in messages_text
        
        # Should ask about payment method
        assert "Як зручніше оплатити" in messages_text

        # Should save customer data in metadata
        assert result.metadata_updates.get("customer_name") == "Іван Петренко"
        assert result.metadata_updates.get("customer_phone") == "0501234567"


# =============================================================================
# handle_confirm_data Tests
# =============================================================================


class TestHandleConfirmData:
    """Tests for CONFIRM_DATA sub-phase."""

    @pytest.mark.parametrize("user_text", [
        "повна оплата",
        "на ФОП",
        "без комісії",
        "повністю сплачу",
    ])
    def test_full_payment_detected(self, user_text):
        """Detects full payment keywords."""
        result = handle_confirm_data(
            user_text=user_text,
            product_price=2500,
            product_size="146-152",
            session_id="session_123"
        )
        
        assert result.next_sub_phase == "SHOW_PAYMENT"
        assert result.metadata_updates.get("payment_method") == "full"
        assert result.metadata_updates.get("payment_amount") == 2500

    @pytest.mark.parametrize("user_text", [
        "передплата",
        "частинами",
        "накладеним",
        "на нп решту",
    ])
    def test_prepay_detected(self, user_text):
        """Detects prepay keywords."""
        result = handle_confirm_data(
            user_text=user_text,
            product_price=2500,
            product_size="146-152",
            session_id="session_123"
        )
        
        assert result.next_sub_phase == "SHOW_PAYMENT"
        assert result.metadata_updates.get("payment_method") == "prepay"
        # Prepay amount is fixed (from config)
        from src.conf.payment_config import PAYMENT_PREPAY_AMOUNT
        assert result.metadata_updates.get("payment_amount") == PAYMENT_PREPAY_AMOUNT

    def test_unknown_input_asks_again(self):
        """Unknown input asks for clarification."""
        result = handle_confirm_data(
            user_text="а можна картою?",
            product_price=2500,
            product_size="146-152",
            session_id="session_123"
        )
        
        assert result.next_sub_phase == "CONFIRM_DATA"  # Stay in same phase
        assert "Підкажіть" in result.messages[0].content

    def test_zero_price_uses_default(self):
        """When price is 0, uses default price for full payment."""
        result = handle_confirm_data(
            user_text="повна оплата",
            product_price=0,
            product_size=None,
            session_id="session_123"
        )
        
        from src.conf.payment_config import PAYMENT_DEFAULT_PRICE
        assert result.metadata_updates.get("payment_amount") == PAYMENT_DEFAULT_PRICE


# =============================================================================
# handle_show_payment Tests
# =============================================================================


class TestHandleShowPayment:
    """Tests for SHOW_PAYMENT sub-phase."""

    @pytest.mark.parametrize("user_text", [
        "оплатила",
        "відправила скрін",
        "готово",
        "переказала",
    ])
    def test_payment_confirmation_detected(self, user_text):
        """Detects payment confirmation keywords."""
        result = handle_show_payment(
            user_text=user_text,
            has_image=False,
            session_id="session_123"
        )
        
        assert result.next_sub_phase == "THANK_YOU"
        assert result.next_state == State.STATE_7_END.value
        assert result.event == "escalation"
        assert result.should_escalate is True
        assert result.metadata_updates.get("payment_confirmed") is True

    def test_image_confirms_payment(self):
        """Image (screenshot) confirms payment."""
        result = handle_show_payment(
            user_text="",
            has_image=True,
            session_id="session_123"
        )
        
        assert result.next_sub_phase == "THANK_YOU"
        assert result.should_escalate is True

    def test_no_confirmation_waits(self):
        """No confirmation keeps waiting."""
        result = handle_show_payment(
            user_text="а скільки йти буде?",
            has_image=False,
            session_id="session_123"
        )
        
        assert result.next_sub_phase == "SHOW_PAYMENT"  # Stay in same phase
        assert "Чекаю скрін" in result.messages[0].content


# =============================================================================
# process_payment_subphase Tests
# =============================================================================


class TestProcessPaymentSubphase:
    """Tests for main dispatcher."""

    def test_request_data_routing(self):
        """Routes to handle_request_data."""
        result = process_payment_subphase(
            sub_phase="REQUEST_DATA",
            user_text="",
            has_image=False,
            customer_data=CustomerData(),
            product_price=2500,
            product_size="146-152",
            session_id="session_123"
        )
        
        assert result.next_sub_phase == "REQUEST_DATA"

    def test_confirm_data_routing(self):
        """Routes to handle_confirm_data."""
        result = process_payment_subphase(
            sub_phase="CONFIRM_DATA",
            user_text="повна оплата",
            has_image=False,
            customer_data=CustomerData(),
            product_price=2500,
            product_size="146-152",
            session_id="session_123"
        )
        
        assert result.next_sub_phase == "SHOW_PAYMENT"

    def test_show_payment_routing(self):
        """Routes to handle_show_payment."""
        result = process_payment_subphase(
            sub_phase="SHOW_PAYMENT",
            user_text="оплатила",
            has_image=False,
            customer_data=CustomerData(),
            product_price=2500,
            product_size="146-152",
            session_id="session_123"
        )
        
        assert result.next_sub_phase == "THANK_YOU"

    def test_thank_you_already_complete(self):
        """THANK_YOU returns complete message."""
        result = process_payment_subphase(
            sub_phase="THANK_YOU",
            user_text="дякую",
            has_image=False,
            customer_data=CustomerData(),
            product_price=2500,
            product_size="146-152",
            session_id="session_123"
        )
        
        assert "оформлено" in result.messages[0].content

    def test_unknown_subphase_fallback(self):
        """Unknown sub-phase falls back to REQUEST_DATA."""
        result = process_payment_subphase(
            sub_phase="INVALID",
            user_text="",
            has_image=False,
            customer_data=CustomerData(),
            product_price=2500,
            product_size="146-152",
            session_id="session_123"
        )
        
        assert result.next_sub_phase == "REQUEST_DATA"


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_extract_customer_data_from_metadata(self):
        """Extracts from metadata."""
        state = {
            "metadata": {
                "customer_name": "Іван",
                "customer_phone": "050123",
                "customer_city": "Київ",
                "customer_nova_poshta": "54",
            }
        }
        
        data = extract_customer_data_from_state(state)
        assert data.name == "Іван"
        assert data.phone == "050123"
        assert data.is_complete is True

    def test_extract_customer_data_from_root(self):
        """Extracts from root level if metadata empty."""
        state = {
            "customer_name": "Іван",
            "customer_phone": "050123",
            "customer_city": "Київ",
            "customer_nova_poshta": "54",
            "metadata": {},
        }
        
        data = extract_customer_data_from_state(state)
        assert data.name == "Іван"

    def test_get_product_info_from_selected(self):
        """Gets from selected_products."""
        state = {
            "selected_products": [
                {"name": "Костюм", "price": 2500, "size": "146-152"}
            ]
        }
        
        price, size = get_product_info_from_state(state)
        assert price == 2500
        assert size == "146-152"

    def test_get_product_info_fallback_to_offered(self):
        """Falls back to offered_products."""
        state = {
            "selected_products": [],
            "offered_products": [
                {"name": "Сукня", "price": 1800, "size": "122-128"}
            ]
        }
        
        price, size = get_product_info_from_state(state)
        assert price == 1800
        assert size == "122-128"

    def test_get_product_info_no_products(self):
        """Returns defaults when no products."""
        state = {}
        
        price, size = get_product_info_from_state(state)
        assert price == 0
        assert size is None
