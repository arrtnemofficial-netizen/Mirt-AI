"""Tests for Order model and validation."""

import pytest

from src.services.data.order_model import (
    CustomerInfo,
    Order,
    OrderItem,
    OrderStatus,
    OrderValidationResult,
    build_missing_data_prompt,
    validate_order_data,
)


class TestCustomerInfo:
    """Test CustomerInfo validation."""

    def test_valid_customer(self):
        customer = CustomerInfo(
            full_name="Іванов Іван Іванович",
            phone="+380501234567",
            city="Київ",
            nova_poshta_branch="25",
        )
        assert customer.full_name == "Іванов Іван Іванович"
        assert customer.phone == "+380501234567"

    def test_phone_normalization_0_format(self):
        customer = CustomerInfo(
            full_name="Іванов Іван",
            phone="0501234567",
            city="Київ",
        )
        assert customer.phone == "+380501234567"

    def test_phone_normalization_380_format(self):
        customer = CustomerInfo(
            full_name="Іванов Іван",
            phone="380501234567",
            city="Київ",
        )
        assert customer.phone == "+380501234567"

    def test_invalid_phone_raises(self):
        with pytest.raises(ValueError):
            CustomerInfo(
                full_name="Іванов Іван",
                phone="123",
                city="Київ",
            )

    def test_short_name_raises(self):
        with pytest.raises(ValueError):
            CustomerInfo(
                full_name="І",
                phone="+380501234567",
                city="Київ",
            )


class TestOrderItem:
    """Test OrderItem."""

    def test_item_total(self):
        item = OrderItem(
            product_id=1,
            product_name="Сукня Анна",
            size="122-128",
            color="синій",
            quantity=2,
            price=1200.0,
        )
        assert item.total == 2400.0

    def test_item_default_quantity(self):
        item = OrderItem(
            product_id=1,
            product_name="Сукня Анна",
            size="122-128",
            color="синій",
            price=1200.0,
        )
        assert item.quantity == 1
        assert item.total == 1200.0


class TestOrder:
    """Test Order model."""

    def test_create_order(self):
        order = Order(
            external_id="session_123",
            customer=CustomerInfo(
                full_name="Іванов Іван",
                phone="+380501234567",
                city="Київ",
                nova_poshta_branch="25",
            ),
            items=[
                OrderItem(
                    product_id=1,
                    product_name="Сукня Анна",
                    size="122-128",
                    color="синій",
                    price=1200.0,
                ),
            ],
        )
        assert order.status == OrderStatus.NEW
        assert order.subtotal == 1200.0
        assert order.total == 1200.0

    def test_order_with_discount(self):
        order = Order(
            external_id="session_123",
            customer=CustomerInfo(
                full_name="Іванов Іван",
                phone="+380501234567",
                city="Київ",
            ),
            items=[
                OrderItem(
                    product_id=1,
                    product_name="Сукня Анна",
                    size="122-128",
                    color="синій",
                    price=1200.0,
                ),
            ],
            discount=100.0,
            delivery_cost=50.0,
        )
        assert order.total == 1150.0  # 1200 - 100 + 50

    def test_to_crm_payload(self):
        order = Order(
            external_id="session_123",
            customer=CustomerInfo(
                full_name="Іванов Іван",
                phone="+380501234567",
                city="Київ",
                nova_poshta_branch="25",
            ),
            items=[
                OrderItem(
                    product_id=1,
                    product_name="Сукня Анна",
                    size="122-128",
                    color="синій",
                    price=1200.0,
                ),
            ],
            source="manychat",
            source_id="mc_12345",
        )
        payload = order.to_crm_payload()

        assert payload["external_id"] == "session_123"
        assert payload["customer"]["name"] == "Іванов Іван"
        assert payload["customer"]["phone"] == "+380501234567"
        assert payload["customer"]["delivery_address"] == "25"
        assert len(payload["items"]) == 1
        assert payload["items"][0]["name"] == "Сукня Анна"
        assert payload["totals"]["total"] == 1200.0
        assert payload["source"] == "manychat"


class TestValidateOrderData:
    """Test validate_order_data function."""

    def test_valid_data(self):
        result = validate_order_data(
            full_name="Іванов Іван Іванович",
            phone="+380501234567",
            city="Київ",
            nova_poshta="25",
            products=[{"product_id": 1, "name": "Сукня", "price": 1200}],
        )
        assert result.is_valid is True
        assert result.can_submit_to_crm is True
        assert len(result.missing_fields) == 0

    def test_missing_name(self):
        result = validate_order_data(
            full_name=None,
            phone="+380501234567",
            city="Київ",
            nova_poshta="25",
            products=[{"product_id": 1}],
        )
        assert result.is_valid is False
        assert "full_name" in result.missing_fields

    def test_missing_phone(self):
        result = validate_order_data(
            full_name="Іванов Іван",
            phone=None,
            city="Київ",
            nova_poshta="25",
            products=[{"product_id": 1}],
        )
        assert result.is_valid is False
        assert "phone" in result.missing_fields

    def test_invalid_phone(self):
        result = validate_order_data(
            full_name="Іванов Іван",
            phone="123",
            city="Київ",
            nova_poshta="25",
            products=[{"product_id": 1}],
        )
        assert result.is_valid is False
        assert "phone" in result.invalid_fields

    def test_missing_products(self):
        result = validate_order_data(
            full_name="Іванов Іван",
            phone="+380501234567",
            city="Київ",
            nova_poshta="25",
            products=[],
        )
        assert result.is_valid is False
        assert "products" in result.missing_fields

    def test_product_without_id(self):
        result = validate_order_data(
            full_name="Іванов Іван",
            phone="+380501234567",
            city="Київ",
            nova_poshta="25",
            products=[{"name": "Сукня"}],
        )
        assert result.is_valid is False
        assert "products[0].product_id" in result.invalid_fields


class TestBuildMissingDataPrompt:
    """Test build_missing_data_prompt function."""

    def test_single_missing_field(self):
        validation = OrderValidationResult(
            is_valid=False,
            missing_fields=["phone"],
        )
        prompt = build_missing_data_prompt(validation)
        assert "телефону" in prompt

    def test_multiple_missing_fields(self):
        validation = OrderValidationResult(
            is_valid=False,
            missing_fields=["full_name", "phone", "nova_poshta"],
        )
        prompt = build_missing_data_prompt(validation)
        assert "ПІБ" in prompt
        assert "телефону" in prompt
        assert "Нової Пошти" in prompt

    def test_no_missing_fields(self):
        validation = OrderValidationResult(
            is_valid=True,
            missing_fields=[],
        )
        prompt = build_missing_data_prompt(validation)
        assert prompt == ""
