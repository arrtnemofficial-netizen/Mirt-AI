"""Centralized constants and enumerations for the MIRT AI system.

This module eliminates magic strings scattered across the codebase,
providing type-safe enums and constants for state machine, tags, and events.
"""
from __future__ import annotations

from enum import Enum


class AgentState(str, Enum):
    """State machine states as defined in system_prompt_full.yaml v6.0-final."""

    STATE0_INIT = "STATE0_INIT"
    STATE1_DISCOVERY = "STATE1_DISCOVERY"
    STATE2_VISION = "STATE2_VISION"
    STATE3_CLARIFY = "STATE3_CLARIFY"
    STATE4_OFFER = "STATE4_OFFER"
    STATE5_COMPARISON = "STATE5_COMPARISON"
    STATE6_SIZING = "STATE6_SIZING"
    STATE7_OBJECTION = "STATE7_OBJECTION"
    STATE8_CHECKOUT = "STATE8_CHECKOUT"
    STATE9_OOD = "STATE9_OOD"

    @classmethod
    def default(cls) -> "AgentState":
        """Return the initial state for new conversations."""
        return cls.STATE0_INIT

    @classmethod
    def from_string(cls, value: str) -> "AgentState":
        """Safely parse state string, falling back to INIT if invalid."""
        try:
            return cls(value)
        except ValueError:
            return cls.STATE0_INIT


class EventType(str, Enum):
    """Agent response event types from OUTPUT_CONTRACT."""

    SIMPLE_ANSWER = "simple_answer"
    OFFER = "offer"
    CLARIFY = "clarify"
    ESCALATION = "escalation"
    CHECKOUT = "checkout"
    OUT_OF_DOMAIN = "out_of_domain"


class EscalationLevel(str, Enum):
    """Escalation severity levels."""

    NONE = "NONE"
    L1 = "L1"  # Basic human handoff
    L2 = "L2"  # Supervisor required
    L3 = "L3"  # Critical / security issue


class MessageRole(str, Enum):
    """Standard message roles in conversation history."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageTag(str, Enum):
    """Tags applied to stored messages for filtering and automation."""

    HUMAN_NEEDED = "humanNeeded-wd"
    FOLLOWUP_PREFIX = "followup-sent-"

    @classmethod
    def followup_tag(cls, index: int) -> str:
        """Generate followup tag for a specific index (1-based)."""
        return f"{cls.FOLLOWUP_PREFIX.value}{index}"

    @classmethod
    def is_followup_tag(cls, tag: str) -> bool:
        """Check if a tag is a followup tag."""
        return tag.startswith(cls.FOLLOWUP_PREFIX.value)


class ModerationFlag(str, Enum):
    """Flags set by content moderation."""

    SAFETY = "safety"
    EMAIL = "email"
    PHONE = "phone"
    PII = "pii"


# Tool names as used in system prompt
class ToolName(str, Enum):
    """Supabase tool identifiers matching system_prompt_full.yaml."""

    SEARCH_BY_QUERY = "T_SUPABASE_SEARCH_BY_QUERY"
    GET_BY_ID = "T_SUPABASE_GET_BY_ID"
    GET_BY_PHOTO_URL = "T_SUPABASE_GET_BY_PHOTO_URL"


# Default values
DEFAULT_MATCH_COUNT = 5
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY = 0.35
MAX_RESPONSE_CHARS = 900
