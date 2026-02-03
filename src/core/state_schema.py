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

from typing import Any, Literal, List, Dict, Optional, MutableMapping
from pydantic import BaseModel, Field, ConfigDict

from src.core.models import AgentResponse, Product, Message
from src.core.state_machine import State, Intent

class StateSchema(BaseModel, MutableMapping):
    """
    Unified Conversation State.
    Strictly validated. No more KeyErrors.
    
    Implements MutableMapping to fully emulate a dictionary,
    ensuring 100% compatibility with legacy code.
    """
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True) 

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
    selected_products: List[Dict[str, Any]] = Field(default_factory=list) 
    offered_products: List[Dict[str, Any]] = Field(default_factory=list)

    # --- Flow Flags ---
    has_image: bool = False
    image_url: Optional[str] = None

    # --- Agent Output ---
    agent_response: Optional[Dict[str, Any]] = None 

    # --- Validation & Retry ---
    step_number: int = Field(default=0, description="Graph step counter")
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
    # --- Integration Results ---
    crm_order_result: Optional[Dict[str, Any]] = None
    tool_plan_result: Optional[Dict[str, Any]] = None
    tool_errors: List[str] = Field(default_factory=list)
    
    # --- Logic Flags ---
    is_first_message: bool = False
    
    # --- Memory System ---
    memory_profile: Optional[Any] = None # Using Any to avoid circular import of UserProfile
    memory_facts: List[str] = Field(default_factory=list)
    memory_context_prompt: Optional[str] = None

    # --- Sitniks CRM ---
    sitniks_chat_id: Optional[str] = None
    sitniks_first_touch_done: bool = False
    
    # --- Internal ---
    temp_context: Optional[Dict[str, Any]] = None
    payment_info_buffer: Optional[Dict[str, Any]] = None # Renamed from _payment_context

    @property
    def state_enum(self) -> State:
        return State.from_string(self.current_state)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)

    # --- MutableMapping Implementation (Ironclad Compatibility) ---

    def __getitem__(self, key: str) -> Any:
        """Get value by key. Raises KeyError (not AttributeError) so state.get(k, default) works."""
        try:
            return getattr(self, key)
        except AttributeError:
            # Pydantic extra fields or legacy checkpoints without some fields
            raise KeyError(key) from None

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __delitem__(self, key: str) -> None:
        # Pydantic models don't easily support deleting fields, 
        # but we can set to None or default if it's optional.
        # For now, just deleting from __dict__ if it exists in extra
        try:
            del self.__dict__[key]
        except KeyError:
             # If it's a model field, set to default? 
             # Safety: Validation error is better than crash?
             pass

    def __iter__(self):
        return iter(self.model_dump())

    def __len__(self):
        return len(self.model_dump())

    def update(self, *args, **kwargs):
        """Dict-like update."""
        data = dict(*args, **kwargs)
        for k, v in data.items():
            setattr(self, k, v)

