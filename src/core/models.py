"""Typed contracts shared by the agent and orchestrator.

This module defines the unified data contracts for:
- Products (with id as canonical field)
- Messages
- Metadata
- AgentResponse (OUTPUT_CONTRACT)

UNIFIED with src/agents/pydantic/models.py to prevent Split Brain.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from typing_extensions import TypedDict

from src.core.state_machine import Intent, State

# =============================================================================
# UNIFIED BASE MODELS (Moved from src/agents/pydantic/models.py)
# =============================================================================

# Type aliases for Pydantic compatibility
IntentType = Literal[*tuple(Intent.__members__.keys())]
StateType = Literal[*tuple(State.__members__.keys())]

EventType = Literal[
    "simple_answer",
    "clarifying_question",
    "multi_option",
    "escalation",
    "end_smalltalk",
]

EscalationLevel = Literal["NONE", "L1", "L2", "L3"]


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


class MessageItem(BaseModel):
    """
    Single message item.
    BLOCK 10: messages[].type = "text", content = "string (plain text, NO markdown)"
    """

    type: Literal["text", "image"] = "text"
    content: str = Field(
        max_length=900,
        description="Plain text (or image URL), NO markdown (**, ##), max 900 chars",
    )


class ResponseMetadata(BaseModel):
    """
    OUTPUT_CONTRACT.metadata - required fields.
    """

    session_id: str = Field(default="", description="Copy from input as-is. NEVER generate!")
    current_state: StateType = Field(default="STATE_0_INIT")
    intent: IntentType = Field(default="UNKNOWN_OR_EMPTY")
    escalation_level: EscalationLevel = Field(default="NONE")

    @field_validator("escalation_level", mode="before")
    @classmethod
    def normalize_escalation_level(cls, v: Any) -> str:
        if not v or v == "":
            return "NONE"
        v_str = str(v).upper().strip()
        if v_str in ("SOFT", "SOFT_ESCALATION"):
            return "L1"
        if v_str in ("HARD", "HARD_ESCALATION"):
            return "L2"
        if v_str in ("NONE", "L1", "L2", "L3"):
            return v_str
        return "NONE"


# =============================================================================
# CORE EXTENSIONS (Business Logic)
# =============================================================================

class Product(ProductMatch):
    """
    Core Product model.
    Inherits from ProductMatch but adds business fields.
    """
    sku: str | None = None
    category: str | None = None

    @property
    def product_id(self) -> int:
        return self.id

    @classmethod
    def from_legacy(cls, data: dict[str, Any]) -> Product:
        if "product_id" in data and "id" not in data:
            data = data.copy()
            data["id"] = data.pop("product_id")
        return cls(**data)


# Alias Message to MessageItem
Message = MessageItem


class Metadata(ResponseMetadata):
    """
    Technical metadata about the conversation step.
    Extends ResponseMetadata with internal fields.
    """
    timestamp: str = ""
    event_trigger: str = ""
    notes: str = ""
    moderation_flags: list[str] = Field(default_factory=list)

    @property
    def state_enum(self) -> State:
        return State.from_string(self.current_state)

    @property
    def intent_enum(self) -> Intent:
        return Intent.from_string(self.intent)

    def is_escalation_state(self) -> bool:
        return self.state_enum.requires_escalation

    # Re-implement validators to ensure they work on subclass if needed
    # (Pydantic inherits validators usually, but mode='before' needs care)
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


class Escalation(BaseModel):
    level: Literal["L1", "L2", "L3"]
    reason: str
    target: str


class DebugInfo(BaseModel):
    state: str | None = None
    intent: str | None = None


class AgentResponse(BaseModel):
    """Unified output contract for the AI agent."""
    event: str
    messages: list[Message]
    products: list[Product] = Field(default_factory=list)
    metadata: Metadata
    escalation: Escalation | None = None
    debug: DebugInfo | None = None


class BaseConversationState(TypedDict, total=False):
    """
    Base conversation state contract (Framework-agnostic).
    """
    # Core conversation data
    messages: list[dict[str, Any]]
    current_state: str
    metadata: dict[str, Any]

    # Dialog Phase
    dialog_phase: str

    # Session identification
    session_id: str
    trace_id: str
    thread_id: str

    # Intent & routing
    detected_intent: str | None
    has_image: bool
    image_url: str | None

    # Products & offers
    selected_products: list[dict[str, Any]]
    offered_products: list[dict[str, Any]]

    # Moderation
    moderation_result: dict[str, Any] | None
    should_escalate: bool
    escalation_reason: str | None
    escalation_level: str | None
    manager_notification_sent: bool

    # Tool execution
    tool_plan_result: dict[str, Any] | None
    tool_errors: list[str]

    # Agent response (PydanticAI output)
    agent_response: dict[str, Any]

    # Validation & self-correction
    validation_errors: list[str]
    retry_count: int
    max_retries: int
    last_error: str | None

    # Payment flow (human-in-the-loop)
    awaiting_human_approval: bool
    approval_type: Literal["payment", "refund", "discount", None]
    approval_data: dict[str, Any] | None
    human_approved: bool | None

    # Time travel support
    saved_checkpoint_id: str | None
    saved_parent_checkpoint_id: str | None
    step_number: int

    # Memory System (Titans-like)
    memory_profile: Any
    memory_facts: list[Any]
    memory_context_prompt: str | None
