"""
Structured Output Models - Based on OUTPUT_CONTRACT from prompts
================================================================================
БЛОК 10: OUTPUT CONTRACT (Final JSON Schema)

Ці моделі відповідають точній схемі з промпта:
- event: enum з 5 значень
- messages: array з type/content
- products: array з id/name/price/size/color/photo_url
- metadata: session_id/current_state/intent/escalation_level

IMPORTED FROM src.core.models TO PREVENT DUPLICATION
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Import Unified Models from Core (Single Source of Truth)
from src.core.models import (
    ProductMatch,
    MessageItem,
    ResponseMetadata,
    EscalationLevel,
    IntentType,
    StateType,
    EventType,
    Intent,
    State,
)


# =============================================================================
# ESCALATION MODEL
# =============================================================================


class EscalationInfo(BaseModel):
    """Escalation details when event='escalation'."""

    reason: str = Field(description="Причина ескалації")
    target: str = Field(default="human_operator")


# =============================================================================
# CUSTOMER DATA (for STATE_5_PAYMENT_DELIVERY)
# =============================================================================


class CustomerDataExtracted(BaseModel):
    """
    Customer data for order.
    """
    name: str | None = Field(default=None, description="ПІБ отримувача")
    phone: str | None = Field(default=None, description="Номер телефону")
    city: str | None = Field(default=None, description="Місто доставки")
    nova_poshta: str | None = Field(default=None, description="Відділення Нової пошти")


# =============================================================================
# OFFER DELIBERATION (Multi-Role Analysis)
# =============================================================================


class OfferDeliberation(BaseModel):
    """
    Multi-role analysis before presenting offer to customer.
    """
    customer_view: str = Field(
        default="", description="Customer Advocate: Is this clear? Does it show value? No pressure?"
    )
    business_view: str = Field(
        default="", description="Business Owner: Is margin healthy? Any upsell opportunity?"
    )
    quality_view: str = Field(
        default="",
        description="Quality Control: Is price from DB? Is size available? Any data issues?",
    )
    confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Confidence in this offer (0.0-1.0). Lower if views conflict.",
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Warnings: 'price_mismatch', 'size_unavailable', 'low_margin', etc.",
    )


# =============================================================================
# SUPPORT RESPONSE (OUTPUT_CONTRACT)
# =============================================================================


class SupportResponse(BaseModel):
    """
    OUTPUT CONTRACT - Final JSON Schema.
    """

    # REQUIRED: event type
    event: EventType = Field(
        description="simple_answer/clarifying_question/multi_option/escalation/end_smalltalk"
    )

    # REQUIRED: messages (min 1)
    messages: list[MessageItem] = Field(
        min_length=1,
        description="Повідомлення для клієнта (plain text, NO markdown, max 900 chars)",
    )

    # REQUIRED: metadata
    metadata: ResponseMetadata = Field(
        description="session_id, current_state, intent, escalation_level"
    )

    # OPTIONAL: products (only if found in CATALOG)
    products: list[ProductMatch] = Field(
        default_factory=list,
        description="Товари ТІЛЬКИ з CATALOG (id, name, price, size, color, photo_url)",
    )

    # OPTIONAL: reasoning for debug
    reasoning: str | None = Field(
        default=None,
        description="Internal debug log (Input -> Intent -> Catalog -> State -> Output)",
    )

    # OPTIONAL: escalation (required if event='escalation')
    escalation: EscalationInfo | None = Field(
        default=None,
        description="Required if event='escalation'",
    )

    # Additional: customer data extracted
    customer_data: CustomerDataExtracted | None = Field(
        default=None,
        description="Дані клієнта з повідомлення (для STATE_5)",
    )

    # Multi-role deliberation for offer validation (STATE_4_OFFER)
    deliberation: OfferDeliberation | None = Field(
        default=None,
        description="Multi-role analysis: customer/business/quality views (for STATE_4_OFFER)",
    )

    @field_validator("messages")
    @classmethod
    def validate_messages_not_empty(cls, v: list[MessageItem]) -> list[MessageItem]:
        if not v:
            raise ValueError("messages[] НЕ МОЖЕ бути порожнім. Завжди >= 1 message.")
        return v


# =============================================================================
# VISION AGENT RESPONSE
# =============================================================================


class VisionResponse(BaseModel):
    """
    Відповідь Vision агента (аналіз фото).
    """

    reply_to_user: str = Field(
        description="Відповідь клієнту про товар на фото",
    )

    identified_product: ProductMatch | None = Field(
        default=None,
        description="Товар визначений на фото",
    )

    alternative_products: list[ProductMatch] = Field(
        default_factory=list,
        description="Альтернативні товари якщо точний не знайдено",
    )

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Впевненість у визначенні",
    )

    needs_clarification: bool = Field(
        default=False,
        description="Чи потрібно уточнення від клієнта",
    )

    clarification_question: str | None = Field(
        default=None,
        description="Питання для уточнення",
    )


# =============================================================================
# PAYMENT AGENT RESPONSE
# =============================================================================


class PaymentResponse(BaseModel):
    """
    Відповідь Payment агента (оформлення замовлення).
    """

    reply_to_user: str = Field(
        description="Відповідь клієнту про оплату/доставку",
    )

    # Data collection status
    customer_data: CustomerDataExtracted | None = Field(
        default=None,
        description="Зібрані дані клієнта",
    )

    missing_fields: list[str] = Field(
        default_factory=list,
        description="Які дані ще потрібні: name, phone, city, nova_poshta",
    )

    # Order status
    order_ready: bool = Field(
        default=False,
        description="Чи готове замовлення до створення в CRM",
    )

    order_total: float = Field(
        default=0.0,
        description="Сума замовлення",
    )

    # Payment
    payment_details_sent: bool = Field(
        default=False,
        description="Чи надіслано реквізити для оплати",
    )

    awaiting_payment_confirmation: bool = Field(
        default=False,
        description="Чи чекаємо підтвердження оплати",
    )


# =============================================================================
# UNIFIED RESPONSE (for backward compatibility)
# =============================================================================


class AgentOutput(BaseModel):
    """
    Unified agent output that matches the existing OUTPUT_CONTRACT.
    Maps to AgentResponse in src/core/models.py.
    """

    event: Literal[
        "reply",
        "checkout",
        "escalation",
        "upsell",
        "end",
    ] = Field(description="Тип події")

    messages: list[dict[str, str]] = Field(
        description="Повідомлення для клієнта",
    )

    products: list[ProductMatch] = Field(
        default_factory=list,
        description="Товари для показу",
    )

    metadata: dict = Field(
        default_factory=dict,
        description="Метадані (state, intent, etc.)",
    )

    escalation: dict | None = Field(
        default=None,
        description="Дані ескалації якщо потрібно",
    )
