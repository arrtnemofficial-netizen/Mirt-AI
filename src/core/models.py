"""Typed contracts shared by the agent and orchestrator.

This module defines the unified data contracts for:
- Products (with id as canonical field)
- Messages
- Metadata
- AgentResponse (OUTPUT_CONTRACT)

It serves as the Single Source of Truth (SSOT) for both domain logic and LLM structured outputs.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.core.state_machine import Intent, State


# =============================================================================
# TYPES & ENUMS
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
# PRODUCT MODEL
# =============================================================================

class Product(BaseModel):
    """
    Product as returned from the catalog tool and exposed to clients.

    Uses `id` as the canonical field (matches OUTPUT_CONTRACT).
    The `product_id` alias is provided for backward compatibility.
    """

    id: int = Field(..., gt=0, description="Product ID from catalog (must exist).")
    name: str = Field(description="Product name exactly as in catalog.")
    size: str = Field(default="", description="Size from catalog sizes.")
    color: str = Field(default="", description="Color from catalog colors.")
    price: float = Field(..., gt=0, description="Price in UAH (must come from catalog).")
    photo_url: str = Field(description="Photo URL from catalog.")
    sku: str | None = None
    category: str | None = None

    @property
    def product_id(self) -> int:
        """Backward compatibility alias for id."""
        return self.id

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            raise ValueError("photo_url must start with https://")
        return v

    @classmethod
    def from_legacy(cls, data: dict[str, Any]) -> Product:
        """Create from legacy format with product_id."""
        if "product_id" in data and "id" not in data:
            data = data.copy()
            data["id"] = data.pop("product_id")
        return cls(**data)


# Alias for Agent usage
ProductMatch = Product


# =============================================================================
# MESSAGE MODEL
# =============================================================================

class Message(BaseModel):
    """Single message chunk to the end user."""

    type: Literal["text", "image"] = "text"
    content: str = Field(
        description="Plain text, NO markdown (**, ##), max 900 chars",
    )


# Alias for Agent usage
MessageItem = Message


# =============================================================================
# METADATA & ESCALATION
# =============================================================================

class Metadata(BaseModel):
    """
    Technical metadata about the conversation step.
    """

    session_id: str = Field(default="", description="Copy from input as-is. NEVER generate!")
    timestamp: str = ""
    current_state: str = Field(
        default="STATE_0_INIT", description="Current FSM state (validated against State enum)"
    )
    intent: str = Field(
        default="UNKNOWN_OR_EMPTY", description="Classified intent (validated against Intent enum)"
    )
    event_trigger: str = ""
    escalation_level: EscalationLevel = "NONE"
    notes: str = ""
    moderation_flags: list[str] = Field(default_factory=list)

    # Additional fields needed for logic
    upsell_flow_active: bool = False
    upsell_base_products: list[dict] = Field(default_factory=list)
    vision_greeted: bool = False
    height_cm: int | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_city: str | None = None
    customer_nova_poshta: str | None = None
    selected_color: str | None = None

    @field_validator("current_state", mode="before")
    @classmethod
    def normalize_state(cls, v: Any) -> str:
        if isinstance(v, State):
            return v.value
        if isinstance(v, str) and v:
            return State.from_string(v).value
        return "STATE_0_INIT"

    @field_validator("intent", mode="before")
    @classmethod
    def normalize_intent(cls, v: Any) -> str:
        if isinstance(v, Intent):
            return v.value
        if isinstance(v, str) and v:
            return Intent.from_string(v).value
        return "UNKNOWN_OR_EMPTY"

    @property
    def state_enum(self) -> State:
        return State.from_string(self.current_state)

    @property
    def intent_enum(self) -> Intent:
        return Intent.from_string(self.intent)


class Escalation(BaseModel):
    """Escalation descriptor when operator handover is needed."""

    level: EscalationLevel
    reason: str
    target: str = "human_operator"


class DebugInfo(BaseModel):
    """Optional debug payload for observability."""
    state: str | None = None
    intent: str | None = None


# =============================================================================
# CUSTOMER DATA (for STATE_5_PAYMENT_DELIVERY)
# =============================================================================

class CustomerDataExtracted(BaseModel):
    """
    Customer data for order.
    """
    name: str | None = Field(default=None, description="Recipient full name")
    phone: str | None = Field(default=None, description="Phone number")
    city: str | None = Field(default=None, description="Delivery city")
    nova_poshta: str | None = Field(default=None, description="Nova Poshta branch")


# =============================================================================
# AGENT RESPONSES (OUTPUT CONTRACTS)
# =============================================================================

class AgentResponse(BaseModel):
    """
    Unified output contract for the AI agent.
    Acts as the base class and the runtime contract.
    """

    event: EventType
    messages: list[Message]
    products: list[Product] = Field(default_factory=list)
    metadata: Metadata
    escalation: Escalation | None = None
    debug: DebugInfo | None = None

    # Optional fields for LLM internal thought process
    reasoning: str | None = Field(
        default=None,
        description="Internal debug log (Input -> Intent -> Catalog -> State -> Output)",
    )
    deliberation: str | None = Field(
        default=None,
        description="Internal deliberation/thinking process",
    )
    customer_data: CustomerDataExtracted | None = Field(
        default=None,
        description="Customer data extracted from message (for STATE_5)",
    )

    @field_validator("messages")
    @classmethod
    def validate_messages_not_empty(cls, v: list[Message]) -> list[Message]:
        if not v:
            raise ValueError("messages[] must not be empty. Always >= 1 message.")
        return v


# Aliases for Agent usage (Backwards Compatibility / Specific Roles)
SupportResponse = AgentResponse


class OfferDeliberation(BaseModel):
    """Structure for offer deliberation."""
    analysis: str


class OfferResponse(AgentResponse):
    """
    Output contract for offer generation with deliberation.
    """
    # Note: We keep simple str deliberation in AgentResponse,
    # but OfferResponse might have had a complex one.
    # For now, we map it to the string field or keep as is if Pydantic allows.
    pass


class VisionResponse(BaseModel):
    """
    Vision agent response (photo analysis).
    """
    reply_to_user: str = Field(
        description="Customer-facing response about the product in the photo",
    )
    identified_product: Product | None = Field(
        default=None,
        description="Identified product in the photo",
    )
    alternative_products: list[Product] = Field(
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
    vision_quality_check: dict[str, Any] | None = Field(
        default=None,
        description="Quality control check data",
    )


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

    payment_quality_check: dict[str, Any] | None = Field(
        default=None,
        description="Quality control check before payment step transition (for STATE_5_PAYMENT_DELIVERY). "
        "Required before showing requisites. "
        "Fields: all_fields_collected, missing_fields, data_quality, normalization_applied, validation_errors, ready_for_payment",
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
