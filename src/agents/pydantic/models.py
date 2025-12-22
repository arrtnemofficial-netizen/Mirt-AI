"""
Structured Output Models - Based on OUTPUT_CONTRACT from registry-managed prompts.
===============================================================================
BLOCK 10: OUTPUT CONTRACT (Final JSON Schema)

These models match the exact prompt schema:
- event: enum with 5 values
- messages: array with type/content
- products: array with id/name/price/size/color/photo_url
- metadata: session_id/current_state/intent/escalation_level
"""

from __future__ import annotations

from typing import Literal

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

    BLOCK 10 validation_rules:
    - products[i].id MUST exist in CATALOG
    - products[i].price MUST be > 0 AND from CATALOG
    - products[i].photo_url MUST start with 'https://' AND from CATALOG
    - products[i].size MUST be in CATALOG.sizes
    """

    id: int = Field(description="Product ID from catalog (must exist).")
    name: str = Field(description="Product name exactly as in catalog.")
    price: float = Field(gt=0, description="Price in UAH (must come from catalog).")
    size: str = Field(description="Size from catalog sizes.")
    color: str = Field(description="Color from catalog colors.")
    photo_url: str = Field(description="Photo URL from catalog.")

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v: str) -> str:
        if not v.startswith("https://"):
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
    - escalation_level: NONE/L1/L2
    """
    session_id: str = Field(default="", description="Copy from input as-is. NEVER generate!")
    current_state: StateType = Field(default="STATE_0_INIT")
    intent: IntentType = Field(default="UNKNOWN_OR_EMPTY")
    escalation_level: EscalationLevel = Field(default="NONE")


# =============================================================================
# ESCALATION MODEL
# =============================================================================


class EscalationInfo(BaseModel):
    """Escalation details when event='escalation'."""
    reason: str = Field(description="Escalation reason")
    target: str = Field(default="human_operator")


# =============================================================================
# CUSTOMER DATA (for STATE_5_PAYMENT_DELIVERY)
# =============================================================================


class CustomerDataExtracted(BaseModel):
    """
    Customer data for order.

    STATE_5_PAYMENT_DELIVERY goals:
    - Collect full name, phone, city, and branch/address
    - Capture payment method
    """
    name: str | None = Field(default=None, description="Recipient full name")
    phone: str | None = Field(default=None, description="Phone number")
    city: str | None = Field(default=None, description="Delivery city")
    nova_poshta: str | None = Field(default=None, description="Nova Poshta branch")


# =============================================================================
# SUPPORT RESPONSE (OUTPUT_CONTRACT)
# =============================================================================


class SupportResponse(BaseModel):
    """
    OUTPUT CONTRACT - Final JSON Schema.

    BLOCK 10 mandatory_fields: ["event", "messages", "metadata"]

    PRE_OUTPUT_CHECKLIST:
    1. Are all products[].id present in catalog?
    2. Are all products[].price > 0 and from catalog?
    3. Is metadata.session_id copied from input?
    4. Does messages[] have at least 1 element?
    5. If event='escalation' -> is escalation.reason filled?
    6. Do all products[].photo_url start with 'https://'? 
    """

    # REQUIRED: event type
    event: EventType = Field(
        description="simple_answer/clarifying_question/multi_option/escalation/end_smalltalk"
    )

    # REQUIRED: messages (min 1)
    messages: list[MessageItem] = Field(
        min_length=1,
        description="Customer-facing message (plain text, no markdown, max 900 chars)",
    )

    # REQUIRED: metadata
    metadata: ResponseMetadata = Field(
        description="session_id, current_state, intent, escalation_level"
    )

    # OPTIONAL: products (only if found in CATALOG)
    products: list[ProductMatch] = Field(
        default_factory=list,
        description="Products must be from catalog (id, name, price, size, color, photo_url)",
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

    # OPTIONAL: deliberation for multi-role pattern
    deliberation: str | None = Field(
        default=None,
        description="Internal deliberation/thinking process",
    )

    # Additional: customer data extracted
    customer_data: CustomerDataExtracted | None = Field(
        default=None,
        description="Customer data extracted from message (for STATE_5)",
    )

    @field_validator("messages")
    @classmethod
    def validate_messages_not_empty(cls, v: list[MessageItem]) -> list[MessageItem]:
        if not v:
            raise ValueError("messages[] must not be empty. Always >= 1 message.")
        return v


# =============================================================================
# OFFER RESPONSE (adds deliberation for STATE_4_OFFER)
# =============================================================================


class OfferResponse(SupportResponse):
    """
    Output contract for offer generation with deliberation.
    """

    deliberation: OfferDeliberation | None = Field(
        default=None,
        description="Multi-role analysis: customer/business/quality views (for STATE_4_OFFER)",
    )


# =============================================================================
# VISION AGENT RESPONSE
# =============================================================================


class VisionResponse(BaseModel):
    """
    Vision agent response (photo analysis).
    """

    reply_to_user: str = Field(
        description="Customer-facing response about the product in the photo",
    )

    identified_product: ProductMatch | None = Field(
        default=None,
        description="Identified product in the photo",
    )

    alternative_products: list[ProductMatch] = Field(
        default_factory=list,
        description="Alternative products if exact match not found",
    )

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score",
    )

    needs_clarification: bool = Field(
        default=False,
        description="Whether clarification is needed from the customer",
    )

    clarification_question: str | None = Field(
        default=None,
        description="Clarification question",
    )


# =============================================================================
# PAYMENT AGENT RESPONSE
# =============================================================================


class PaymentResponse(BaseModel):
    """
    Payment agent response (order processing).
    """

    reply_to_user: str = Field(
        description="Customer-facing response about payment/delivery",
    )

    # Data collection status
    customer_data: CustomerDataExtracted | None = Field(
        default=None,
        description="Collected customer data",
    )

    missing_fields: list[str] = Field(
        default_factory=list,
        description="Missing fields: name, phone, city, nova_poshta",
    )

    # Order status
    order_ready: bool = Field(
        default=False,
        description="Whether order is ready for CRM creation",
    )

    order_total: float = Field(
        default=0.0,
        description="Order total",
    )

    # Payment
    payment_details_sent: bool = Field(
        default=False,
        description="Whether payment requisites were sent",
    )

    awaiting_payment_confirmation: bool = Field(
        default=False,
        description="Whether payment confirmation is pending",
    )

    payment_proof_detected: bool = Field(
        default=False,
        description="Whether payment proof is present in current message",
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
    ] = Field(description="Event type")

    messages: list[dict[str, str]] = Field(
        description="Customer-facing messages",
    )

    products: list[ProductMatch] = Field(
        default_factory=list,
        description="Products to display",
    )

    metadata: dict = Field(
        default_factory=dict,
        description="Metadata (state, intent, etc.)",
    )

    escalation: dict | None = Field(
        default=None,
        description="Escalation data if needed",
    )
