"""
Input Validator - валідація вхідних metadata.
=============================================
Pydantic схеми для валідації metadata у вебхуках
перед викликом агента.

Використання:
    from src.core.input_validator import validate_input_metadata, InputMetadata
    
    # В webhook handler
    validated = validate_input_metadata(raw_metadata)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from src.core.state_machine import State, Intent, EscalationLevel, normalize_state

logger = logging.getLogger(__name__)


class InputMetadata(BaseModel):
    """
    Validated input metadata from webhook/bot.
    Clamps values to valid enums before agent call.
    """
    session_id: str = Field(default="", description="Unique session/conversation ID")
    current_state: State = Field(default=State.STATE_0_INIT)
    intent: Optional[Intent] = Field(default=None, description="Pre-classified intent (optional)")
    channel: str = Field(default="unknown", description="Source channel: telegram/instagram/web")
    language: str = Field(default="uk", description="User language code")
    has_image: bool = Field(default=False)
    image_url: Optional[str] = None
    escalation_level: EscalationLevel = Field(default=EscalationLevel.NONE)
    moderation_flags: List[str] = Field(default_factory=list)
    
    @field_validator("current_state", mode="before")
    @classmethod
    def normalize_state_value(cls, v: Any) -> State:
        """Normalize state string to State enum."""
        if isinstance(v, State):
            return v
        if isinstance(v, str):
            return normalize_state(v)
        return State.STATE_0_INIT
    
    @field_validator("intent", mode="before")
    @classmethod
    def normalize_intent_value(cls, v: Any) -> Optional[Intent]:
        """Normalize intent string to Intent enum."""
        if v is None:
            return None
        if isinstance(v, Intent):
            return v
        if isinstance(v, str):
            return Intent.from_string(v)
        return None
    
    @field_validator("escalation_level", mode="before")
    @classmethod
    def normalize_escalation(cls, v: Any) -> EscalationLevel:
        """Normalize escalation level."""
        if isinstance(v, EscalationLevel):
            return v
        if isinstance(v, str):
            try:
                return EscalationLevel(v.upper())
            except ValueError:
                return EscalationLevel.NONE
        return EscalationLevel.NONE
    
    @field_validator("channel", mode="before")
    @classmethod
    def normalize_channel(cls, v: Any) -> str:
        """Normalize channel to lowercase."""
        if not v:
            return "unknown"
        return str(v).lower().strip()
    
    def to_agent_metadata(self) -> Dict[str, Any]:
        """Convert to dict format expected by agent."""
        return {
            "session_id": self.session_id,
            "current_state": self.current_state.value,
            "intent": self.intent.value if self.intent else None,
            "channel": self.channel,
            "language": self.language,
            "has_image": self.has_image,
            "image_url": self.image_url,
            "escalation_level": self.escalation_level.value,
            "moderation_flags": self.moderation_flags,
        }


class WebhookInput(BaseModel):
    """
    Full webhook input validation.
    Used in src/server/main.py and src/integrations/manychat/webhook.py
    """
    text: str = Field(default="", description="User message text")
    session_id: str = Field(default="")
    metadata: InputMetadata = Field(default_factory=InputMetadata)
    image_url: Optional[str] = None
    
    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, v: Any) -> str:
        """Ensure text is string."""
        if v is None:
            return ""
        return str(v).strip()
    
    @field_validator("session_id", mode="before")
    @classmethod
    def normalize_session_id(cls, v: Any) -> str:
        """Ensure session_id is string."""
        if v is None:
            return ""
        return str(v).strip()


def validate_input_metadata(raw: Dict[str, Any]) -> InputMetadata:
    """
    Validate and normalize raw metadata dict.
    Returns InputMetadata with clamped enum values.
    """
    try:
        return InputMetadata(**raw)
    except Exception as e:
        logger.warning("Failed to validate input metadata: %s, using defaults", e)
        return InputMetadata()


def validate_webhook_input(raw: Dict[str, Any]) -> WebhookInput:
    """
    Validate full webhook input.
    Returns WebhookInput with normalized values.
    """
    try:
        return WebhookInput(**raw)
    except Exception as e:
        logger.warning("Failed to validate webhook input: %s", e)
        return WebhookInput(text=raw.get("text", ""), session_id=raw.get("session_id", ""))
