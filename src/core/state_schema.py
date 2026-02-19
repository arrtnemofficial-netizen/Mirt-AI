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

from typing import Any, List, Dict, Optional, MutableMapping

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing_extensions import TypedDict

from src.core.models import AgentResponse
from src.core.state_machine import (
    State,
    STATE_TO_ALLOWED_PHASES,
    VALID_DIALOG_PHASES,
    get_default_dialog_phase_for_state,
)


RETRY_BUFFER = 1


class StateMetadata(TypedDict, total=False):
    session_id: str
    channel: str
    language: str
    vision_greeted: bool
    has_image: bool
    image_url: str | None
    dialog_phase_history: list[str]


class ModerationResult(TypedDict, total=False):
    status: str
    score: float
    reason: str
    categories: list[str]
    should_escalate: bool


class ToolPlanResult(TypedDict, total=False):
    status: str
    selected_tool: str
    confidence: float
    reason: str
    steps: list[str]


class LegacyAgentResponse(TypedDict, total=False):
    event: str
    messages: list[dict[str, Any]]
    products: list[dict[str, Any]]
    metadata: dict[str, Any]

class StateSchema(BaseModel, MutableMapping):
    """
    Unified Conversation State.
    Strictly validated. No more KeyErrors.
    
    Implements MutableMapping to fully emulate a dictionary,
    ensuring 100% compatibility with legacy code.
    """
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

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
    metadata: StateMetadata = Field(default_factory=dict)

    # --- Commerce ---
    selected_products: List[Dict[str, Any]] = Field(default_factory=list) 
    offered_products: List[Dict[str, Any]] = Field(default_factory=list)

    # --- Flow Flags ---
    has_image: bool = False
    image_url: Optional[str] = None

    # --- Agent Output ---
    agent_response: Optional[AgentResponse | LegacyAgentResponse] = None

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
    moderation_result: Optional[ModerationResult] = None
    # --- Integration Results ---
    crm_order_result: Optional[Dict[str, Any]] = None
    tool_plan_result: Optional[ToolPlanResult] = None
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

    # Legacy unknown keys from old checkpoints are preserved here.
    legacy_extra: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_legacy_extra(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        known_fields = set(cls.model_fields)
        payload = dict(value)
        provided_legacy = payload.get("legacy_extra")
        legacy_bucket: dict[str, Any] = (
            dict(provided_legacy) if isinstance(provided_legacy, dict) else {}
        )

        for key in list(payload.keys()):
            if key not in known_fields:
                legacy_bucket[key] = payload.pop(key)

        payload["legacy_extra"] = legacy_bucket
        return payload

    @field_validator("current_state", mode="before")
    @classmethod
    def _normalize_current_state(cls, value: Any) -> str:
        if isinstance(value, State):
            return value.value
        return State.from_string(str(value or "")).value

    @field_validator("dialog_phase", mode="before")
    @classmethod
    def _normalize_dialog_phase(cls, value: Any) -> str:
        phase = str(value or "").strip().upper()
        return phase or "INIT"

    @model_validator(mode="after")
    def _validate_invariants(self) -> "StateSchema":
        state_enum = State.from_string(self.current_state)
        self.current_state = state_enum.value

        if self.dialog_phase not in VALID_DIALOG_PHASES:
            self.dialog_phase = get_default_dialog_phase_for_state(state_enum)

        allowed_phases = STATE_TO_ALLOWED_PHASES.get(state_enum, frozenset())
        if allowed_phases and self.dialog_phase not in allowed_phases:
            self.dialog_phase = get_default_dialog_phase_for_state(state_enum)

        if self.retry_count > self.max_retries + RETRY_BUFFER:
            raise ValueError(
                "retry_count exceeds max_retries + buffer "
                f"({self.retry_count} > {self.max_retries} + {RETRY_BUFFER})"
            )

        metadata_has_image = self.metadata.get("has_image")
        metadata_image_url = self.metadata.get("image_url")

        if metadata_has_image is not None and bool(metadata_has_image) != self.has_image:
            raise ValueError(
                "metadata.has_image conflicts with canonical has_image"
            )

        normalized_meta_image_url = (
            metadata_image_url.strip() if isinstance(metadata_image_url, str) else metadata_image_url
        )
        if normalized_meta_image_url == "":
            normalized_meta_image_url = None

        if normalized_meta_image_url != self.image_url:
            if normalized_meta_image_url is not None or self.image_url is not None:
                raise ValueError(
                    "metadata.image_url conflicts with canonical image_url"
                )

        return self

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
            if key in self.legacy_extra:
                return self.legacy_extra[key]
            raise KeyError(key) from None

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self.model_fields:
            setattr(self, key, value)
            return
        self.legacy_extra[key] = value

    def __delitem__(self, key: str) -> None:
        # Pydantic models don't easily support deleting fields, 
        # but we can set to None or default if it's optional.
        # For now, just deleting from __dict__ if it exists in extra
        if key in self.legacy_extra:
            del self.legacy_extra[key]
            return
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
            self[k] = v
