"""
Structured Output Models - Based on OUTPUT_CONTRACT from prompts
================================================================================
БЛОК 10: OUTPUT CONTRACT (Final JSON Schema)

Ці моделі відповідають точній схемі з промпта:
- event: enum з 5 значень
- messages: array з type/content
- products: array з id/name/price/size/color/photo_url
- metadata: session_id/current_state/intent/escalation_level
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Import from centralized state machine to avoid duplication
from src.core.state_machine import Intent, State


# Type aliases for Pydantic compatibility - unpack tuple for Literal
IntentType = Literal[*tuple(Intent.__members__.keys())]
StateType = Literal[*tuple(State.__members__.keys())]

# =============================================================================
# EVENTS (BLOCK 10: OUTPUT_CONTRACT.event)
# =============================================================================

EventType = Literal[
    "simple_answer",
    "clarifying_question",
    "multi_option",
    "escalation",
    "end_smalltalk",
]

EscalationLevel = Literal["NONE", "L1", "L2", "L3"]


# =============================================================================
# PRODUCT MODEL (OUTPUT_CONTRACT.products)
# =============================================================================


class ProductMatch(BaseModel):
    """
    Product from CATALOG.

    Relaxed validation for Vision agent - only name is required.
    Price/color can be filled later from DB lookup.
    """

    id: int = Field(default=0, description="Product ID (0 if unknown, will lookup by name)")
    name: str = Field(description="Назва товару точно як в CATALOG")
    price: float = Field(
        default=0.0, ge=0, description="Ціна в грн (0 = варіативна, дізнатись з DB)"
    )
    size: str | None = Field(default=None, description="Розмір (якщо клієнт вказав)")
    color: str = Field(default="", description="Колір (може бути порожнім)")
    photo_url: str = Field(default="", description="URL фото з CATALOG (може бути порожнім)")

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            raise ValueError("photo_url MUST start with 'https://'")
        return v


# =============================================================================
# MESSAGE MODEL (OUTPUT_CONTRACT.messages)
# =============================================================================


class MessageItem(BaseModel):
    """
    Single message item.

    BLOCK 10: messages[].type = "text", content = "string (plain text, NO markdown)"
    """

    type: Literal["text"] = "text"
    content: str = Field(
        max_length=900,
        description="Plain text, NO markdown (**, ##), max 900 chars",
    )


# =============================================================================
# METADATA MODEL (OUTPUT_CONTRACT.metadata)
# =============================================================================


class ResponseMetadata(BaseModel):
    """
    OUTPUT_CONTRACT.metadata - required fields.

    Rules:
    - session_id: Copy from input as-is. If null -> ''
    - current_state: MUST be valid STATE_NAME
    - intent: MUST be valid INTENT_LABEL
    - escalation_level: NONE/L1/L2/L3 (normalizes SOFT→L1, HARD→L2)
    """

    session_id: str = Field(default="", description="Copy from input as-is. NEVER generate!")
    current_state: StateType = Field(default="STATE_0_INIT")
    intent: IntentType = Field(default="UNKNOWN_OR_EMPTY")
    escalation_level: EscalationLevel = Field(default="NONE")

    @field_validator("escalation_level", mode="before")
    @classmethod
    def normalize_escalation_level(cls, v: Any) -> str:
        """
        Normalize escalation_level to allowed enum values.
        
        Accepts: "SOFT"/"soft" → "L1", "HARD"/"hard" → "L2", empty/None → "NONE".
        This ensures backward compatibility if legacy code writes "SOFT"/"HARD".
        
        Returns: Canonical escalation level ("NONE", "L1", "L2", or "L3").
        """
        if not v or v == "":
            return "NONE"
        
        v_str = str(v).upper().strip()
        
        # Map legacy UX modes to escalation levels
        if v_str in ("SOFT", "SOFT_ESCALATION"):
            return "L1"
        if v_str in ("HARD", "HARD_ESCALATION"):
            return "L2"
        
        # Validate against allowed values
        if v_str in ("NONE", "L1", "L2", "L3"):
            return v_str
        
        # Unknown value → default to NONE (don't crash in production)
        return "NONE"


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

    STATE_5_PAYMENT_DELIVERY goals:
    - Зібрати ПІБ, телефон, місто та відділення/адресу
    - Зафіксувати спосіб оплати
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

    Used in STATE_4_OFFER to validate offers from multiple perspectives:
    - Customer Advocate: clarity, value, no pressure
    - Business Owner: margin check, upsell potential
    - Quality Control: price/size/model validation against DB
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

    BLOCK 10 mandatory_fields: ["event", "messages", "metadata"]

    PRE_OUTPUT_CHECKLIST:
    1. Чи всі products[].id є в CATALOG?
    2. Чи всі products[].price > 0 і взяті з CATALOG?
    3. Чи metadata.session_id скопійовано з input?
    4. Чи messages[] має >= 1 елемент?
    5. Якщо event='escalation' -> чи заповнено escalation.reason?
    6. Чи всі products[].photo_url починаються з 'https://'?
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
