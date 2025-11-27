"""Typed contracts shared by the agent and orchestrator.

This module defines the unified data contracts for:
- Products (with id as canonical field)
- Messages
- Metadata
- AgentResponse (OUTPUT_CONTRACT)
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.state_machine import EscalationLevel, State, Intent


class Product(BaseModel):
    """
    Product as returned from the catalog tool and exposed to clients.
    
    Uses `id` as the canonical field (matches OUTPUT_CONTRACT).
    The `product_id` alias is provided for backward compatibility.
    """
    id: int = Field(..., gt=0, description="Product ID")
    name: str
    size: str = ""
    color: str = ""
    price: float = Field(..., gt=0)
    photo_url: str
    sku: Optional[str] = None
    category: Optional[str] = None

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
    def from_legacy(cls, data: Dict[str, Any]) -> "Product":
        """Create from legacy format with product_id."""
        if "product_id" in data and "id" not in data:
            data = data.copy()
            data["id"] = data.pop("product_id")
        return cls(**data)


class Message(BaseModel):
    """Single message chunk to the end user."""

    type: Literal["text", "image"] = "text"
    content: str


class Metadata(BaseModel):
    """
    Technical metadata about the conversation step.
    
    Note on types:
        current_state and intent are stored as str for JSON serialization compatibility,
        but are validated and normalized to known enum values via field_validators.
        Use state_enum/intent_enum properties for type-safe access.
    
    Example:
        metadata = Metadata(current_state="STATE_0_INIT", intent="GREETING_ONLY")
        state: State = metadata.state_enum  # Type-safe enum access
        intent: Intent = metadata.intent_enum
    """

    session_id: str = ""
    timestamp: str = ""
    current_state: str = Field(
        default="STATE_0_INIT", 
        description="Current FSM state (validated against State enum)"
    )
    intent: str = Field(
        default="UNKNOWN_OR_EMPTY", 
        description="Classified intent (validated against Intent enum)"
    )
    event_trigger: str = ""
    escalation_level: Literal["NONE", "L1", "L2", "L3"] = "NONE"
    notes: str = ""
    moderation_flags: List[str] = Field(default_factory=list)
    
    @field_validator("current_state", mode="before")
    @classmethod
    def normalize_state(cls, v: Any) -> str:
        """
        Normalize state to string, validating against State enum.
        Accepts: State enum, string (any format), None.
        Returns: Canonical state string (e.g., "STATE_0_INIT").
        """
        if isinstance(v, State):
            return v.value
        if isinstance(v, str) and v:
            return State.from_string(v).value
        return "STATE_0_INIT"
    
    @field_validator("intent", mode="before")
    @classmethod
    def normalize_intent(cls, v: Any) -> str:
        """
        Normalize intent to string, validating against Intent enum.
        Accepts: Intent enum, string (any case), None.
        Returns: Canonical intent string (e.g., "GREETING_ONLY").
        """
        if isinstance(v, Intent):
            return v.value
        if isinstance(v, str) and v:
            return Intent.from_string(v).value
        return "UNKNOWN_OR_EMPTY"
    
    @property
    def state_enum(self) -> State:
        """Get current_state as State enum (type-safe access)."""
        return State.from_string(self.current_state)
    
    @property
    def intent_enum(self) -> Intent:
        """Get intent as Intent enum (type-safe access)."""
        return Intent.from_string(self.intent)
    
    def is_escalation_state(self) -> bool:
        """Check if current state requires escalation."""
        return self.state_enum.requires_escalation


class Escalation(BaseModel):
    """Escalation descriptor when operator handover is needed."""

    level: Literal["L1", "L2", "L3"]
    reason: str
    target: str


class DebugInfo(BaseModel):
    """Optional debug payload for observability."""

    state: Optional[str] = None
    intent: Optional[str] = None


class AgentResponse(BaseModel):
    """Unified output contract for the AI agent."""

    event: str
    messages: List[Message]
    products: List[Product] = Field(default_factory=list)
    metadata: Metadata
    escalation: Optional[Escalation] = None
    debug: Optional[DebugInfo] = None
