"""Typed contracts shared by the agent and orchestrator."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class Product(BaseModel):
    """Product as returned from the catalog tool and exposed to clients."""

    product_id: int
    name: str
    size: str
    color: str
    price: float
    photo_url: str
    sku: Optional[str] = None
    category: Optional[str] = None


class Message(BaseModel):
    """Single message chunk to the end user."""

    type: Literal["text", "image"] = "text"
    content: str


class Metadata(BaseModel):
    """Technical metadata about the conversation step."""

    session_id: str = ""
    timestamp: str = ""
    current_state: str
    event_trigger: str = ""
    escalation_level: Literal["NONE", "L1", "L2", "L3"] = "NONE"
    notes: str = ""
    moderation_flags: List[str] = Field(default_factory=list)


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
