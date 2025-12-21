"""
Input Validator - validation for incoming metadata.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.core.state_machine import EscalationLevel, Intent, State, normalize_state


logger = logging.getLogger(__name__)


class InputMetadata(BaseModel):
    """
    Validated input metadata from webhook/bot.
    Clamps values to valid enums before agent call.
    """

    session_id: str = Field(default="", description="Unique session/conversation ID")
    current_state: State = Field(default=State.STATE_0_INIT)
    intent: Intent | None = Field(default=None, description="Pre-classified intent (optional)")
    channel: str = Field(default="unknown", description="Source channel: telegram/instagram/web")
    language: str = Field(default="uk", description="User language code")
    has_image: bool = Field(default=False)
    image_url: str | None = None
    escalation_level: EscalationLevel = Field(default=EscalationLevel.NONE)
    moderation_flags: list[str] = Field(default_factory=list)

    @field_validator("has_image", mode="before")
    @classmethod
    def auto_detect_image(cls, v: Any, info) -> bool:
        """Auto-detect has_image from image_url if not explicitly set."""
        if v:
            return True
        # Check if image_url is present in the data being validated
        data = info.data if hasattr(info, 'data') else {}
        image_url = data.get("image_url")
        if image_url and isinstance(image_url, str) and image_url.strip():
            return True
        return bool(v)

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
    def normalize_intent_value(cls, v: Any) -> Intent | None:
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

    def to_agent_metadata(self) -> dict[str, Any]:
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
    image_url: str | None = None

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


def validate_input_metadata(raw: dict[str, Any]) -> InputMetadata:
    """
    Validate and normalize raw metadata dict.
    Returns InputMetadata with clamped enum values.
    """
    try:
        return InputMetadata(**raw)
    except Exception as e:
        logger.warning("Failed to validate input metadata: %s, using defaults", e)
        return InputMetadata()


def validate_webhook_input(raw: dict[str, Any]) -> WebhookInput:
    """
    Validate full webhook input.
    Returns WebhookInput with normalized values.
    """
    try:
        return WebhookInput(**raw)
    except Exception as e:
        logger.warning("Failed to validate webhook input: %s", e)
        return WebhookInput(text=raw.get("text", ""), session_id=raw.get("session_id", ""))
