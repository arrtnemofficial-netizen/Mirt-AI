"""
SSOT State Schema (Pydantic V2).
================================
This is the Strict Typing Foundation (Phase 1).
It replaces loose TypedDicts with validated Pydantic models.

FUTURE MIGRATION:
1. Use this model in LangGraph state definition.
2. Replace `state.get("key")` with `state.key`.
"""

from __future__ import annotations

from typing import Any, Literal, List, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict

from src.core.models import AgentResponse, Product, Message
from src.core.state_machine import State, Intent

class StateSchema(BaseModel):
    """
    Unified Conversation State.
    Strictly validated. No more KeyErrors.
    """
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True) # Allow extra for gradual migration

    # --- Core Identifiers ---
    session_id: str
    trace_id: str = Field(default="")
    thread_id: str = Field(default="")

    # --- State Machine ---
    current_state: str = Field(default=State.STATE_0_INIT.value)
    dialog_phase: str = Field(default="INIT")
    detected_intent: Optional[str] = None

    # --- Data ---
    messages: List[Any] = Field(default_factory=list) # Can be Dict or BaseMessage objects
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # --- Commerce ---
    selected_products: List[Dict[str, Any]] = Field(default_factory=list) # Should be List[Product] later
    offered_products: List[Dict[str, Any]] = Field(default_factory=list)

    # --- Flow Flags ---
    has_image: bool = False
    image_url: Optional[str] = None

    # --- Agent Output ---
    agent_response: Optional[Dict[str, Any]] = None # Serialized AgentResponse

    # --- Validation & Retry ---
    validation_errors: List[str] = Field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    last_error: Optional[str] = None

    # --- HITL (Payment) ---
    awaiting_human_approval: bool = False
    approval_type: Optional[str] = None
    approval_data: Optional[Dict[str, Any]] = None
    human_approved: Optional[bool] = None

    # --- Moderation ---
    should_escalate: bool = False
    escalation_reason: Optional[str] = None
    moderation_result: Optional[Dict[str, Any]] = None

    @property
    def state_enum(self) -> State:
        return State.from_string(self.current_state)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)

    def __getitem__(self, item: str) -> Any:
        """Legacy compatibility: allow dict-like access."""
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        """Legacy compatibility: allow .get() access."""
        return getattr(self, item, default)

    def __setitem__(self, key: str, value: Any) -> None:
        """Legacy compatibility: allow dict-like assignment."""
        setattr(self, key, value)
