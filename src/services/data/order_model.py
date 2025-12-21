"""Order model for CRM integration.

This module defines the Order data structure that will be sent to Snitkix CRM
or other order management systems.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class OrderStatus(str, Enum):
    """Order status for CRM."""

    NEW = "new"  # Нове замовлення
    PENDING_PAYMENT = "pending_payment"  # Очікує оплати
    PAID = "paid"  # Оплачено
    PROCESSING = "processing"  # В обробці
    SHIPPED = "shipped"  # Відправлено
    DELIVERED = "delivered"  # Доставлено
    CANCELLED = "cancelled"  # Скасовано
    RETURNED = "returned"  # Повернуто


class PaymentMethod(str, Enum):
    """Payment methods supported."""

    FULL_PREPAY = "full_prepay"  # Повна передоплата
    PARTIAL_PREPAY = "partial_prepay"  # Передплата 200 грн
    CASH_ON_DELIVERY = "cash_on_delivery"  # Накладений платіж


class DeliveryMethod(str, Enum):
    """Delivery methods supported."""

    NOVA_POSHTA = "nova_poshta"  # Нова Пошта
    NOVA_POSHTA_COURIER = "nova_poshta_courier"  # Нова Пошта кур'єр
    UKRPOSHTA = "ukrposhta"  # Укрпошта
    SELF_PICKUP = "self_pickup"  # Самовивіз


class OrderItem(BaseModel):
    """Single item in the order."""

    product_id: int
    product_name: str
    sku: str | None = None
    size: str
    color: str
    quantity: int = 1
    price: float

    @property
    def total(self) -> float:
        return self.price * self.quantity


class CustomerInfo(BaseModel):
    """Customer information for the order."""

    full_name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(..., pattern=r"^\+380\d{9}$")
    email: str | None = None
    city: str = Field(..., min_length=2, max_length=50)
    nova_poshta_branch: str | None = None
    nova_poshta_address: str | None = None

    # ManyChat/Telegram IDs for tracking
    manychat_id: str | None = None
    telegram_id: str | None = None

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        """Normalize phone to +380XXXXXXXXX format."""
        if not v:
            raise ValueError("Phone is required")

        # Remove all non-digits
        digits = re.sub(r"\D", "", v)

        if digits.startswith("380") and len(digits) == 12:
            return f"+{digits}"
        elif digits.startswith("0") and len(digits) == 10:
            return f"+38{digits}"
        elif len(digits) == 9:
            return f"+380{digits}"
        elif digits.startswith("+380") and len(digits) == 13:
            return v  # Already correct format

        raise ValueError(f"Invalid phone format: {v}")


class Order(BaseModel):
    """Complete order for CRM."""

    # Order identification
    order_id: str | None = None  # Will be assigned by CRM
    external_id: str  # Our internal ID (e.g., session_id)

    # Customer
    customer: CustomerInfo

    # Items
    items: list[OrderItem] = Field(..., min_length=1)

    # Pricing
    subtotal: float = 0.0
    discount: float = 0.0
    delivery_cost: float = 0.0

    # Payment & Delivery
    payment_method: PaymentMethod = PaymentMethod.FULL_PREPAY
    delivery_method: DeliveryMethod = DeliveryMethod.NOVA_POSHTA

    # Status
    status: OrderStatus = OrderStatus.NEW

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None

    # Source tracking
    source: str = "mirt_ai"  # mirt_ai, manychat, telegram
    source_id: str | None = None  # ManyChat subscriber ID or Telegram user ID

    # Notes
    customer_notes: str | None = None
    internal_notes: str | None = None

    def model_post_init(self, __context) -> None:
        """Calculate totals after initialization."""
        if self.subtotal == 0.0:
            self.subtotal = sum(item.total for item in self.items)

    @property
    def total(self) -> float:
        """Calculate total order amount."""
        return self.subtotal - self.discount + self.delivery_cost

    def to_crm_payload(self) -> dict:
        """Convert to CRM-compatible payload format.

        This format is compatible with most CRM systems including Snitkix.
        """
        return {
            "external_id": self.external_id,
            "customer": {
                "name": self.customer.full_name,
                "phone": self.customer.phone,
                "email": self.customer.email,
                "city": self.customer.city,
                "delivery_address": self.customer.nova_poshta_branch
                or self.customer.nova_poshta_address,
            },
            "items": [
                {
                    "product_id": item.product_id,
                    "name": item.product_name,
                    "sku": item.sku,
                    "size": item.size,
                    "color": item.color,
                    "quantity": item.quantity,
                    "price": item.price,
                }
                for item in self.items
            ],
            "totals": {
                "subtotal": self.subtotal,
                "discount": self.discount,
                "delivery": self.delivery_cost,
                "total": self.total,
            },
            "payment_method": self.payment_method.value,
            "delivery_method": self.delivery_method.value,
            "status": self.status.value,
            "source": self.source,
            "source_id": self.source_id,
            "notes": self.customer_notes,
            "created_at": self.created_at.isoformat(),
        }


class OrderValidationResult(BaseModel):
    """Result of order data validation."""

    is_valid: bool
    missing_fields: list[str] = Field(default_factory=list)
    invalid_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def can_submit_to_crm(self) -> bool:
        """Check if order has enough data for CRM submission."""
        return self.is_valid and len(self.missing_fields) == 0


def validate_order_data(
    full_name: str | None,
    phone: str | None,
    city: str | None,
    nova_poshta: str | None,
    products: list[dict],
) -> OrderValidationResult:
    """Validate order data before CRM submission.

    Args:
        full_name: Customer full name
        phone: Customer phone number
        city: Delivery city
        nova_poshta: Nova Poshta branch number
        products: List of product dicts with product_id, name, price, size, color

    Returns:
        OrderValidationResult with validation status and issues
    """
    missing = []
    invalid = []
    warnings = []

    # Required fields
    if not full_name or len(full_name.strip()) < 2:
        missing.append("full_name")

    if not phone:
        missing.append("phone")
    else:
        # Validate phone format
        digits = re.sub(r"\D", "", phone)
        if len(digits) < 9 or len(digits) > 12:
            invalid.append("phone")

    if not city or len(city.strip()) < 2:
        missing.append("city")

    if not nova_poshta:
        missing.append("nova_poshta")

    # Products validation
    if not products or len(products) == 0:
        missing.append("products")
    else:
        for i, product in enumerate(products):
            if not product.get("product_id"):
                invalid.append(f"products[{i}].product_id")
            if not product.get("price"):
                warnings.append(f"products[{i}].price is missing")

    is_valid = len(missing) == 0 and len(invalid) == 0

    return OrderValidationResult(
        is_valid=is_valid,
        missing_fields=missing,
        invalid_fields=invalid,
        warnings=warnings,
    )


def build_missing_data_prompt(validation: OrderValidationResult) -> str:
    """Build a prompt asking for missing data.

    Args:
        validation: OrderValidationResult from validate_order_data

    Returns:
        Ukrainian prompt asking for missing fields
    """
    from src.core.prompt_registry import get_snippet_by_header

    def _get_msg(header: str, default: str = "") -> str:
        s = get_snippet_by_header(header)
        return s[0] if s else default

    prompts = []
    field_prompts = {
        "full_name": _get_msg("AUTOMATION_MISSING_DATA_FULL_NAME", "ПІБ"),
        "phone": _get_msg("AUTOMATION_MISSING_DATA_PHONE", "Телефон"),
        "city": _get_msg("AUTOMATION_MISSING_DATA_CITY", "Місто"),
        "nova_poshta": _get_msg("AUTOMATION_MISSING_DATA_NOVA_POSHTA", "НП"),
        "products": _get_msg("AUTOMATION_MISSING_DATA_PRODUCTS", "Товари"),
    }

    for field in validation.missing_fields:
        if field in field_prompts:
            prompts.append(field_prompts[field])

    if not prompts:
        return ""

    if len(prompts) == 1:
        tmpl = _get_msg("AUTOMATION_MISSING_DATA_SINGLE_TEMPLATE", "Please provide {field}")
        return tmpl.format(field=prompts[0])

    tmpl = _get_msg("AUTOMATION_MISSING_DATA_MULTI_TEMPLATE", "Please provide: {fields}")
    return tmpl.format(fields=", ".join(prompts))
