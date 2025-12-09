"""Centralized constants and enumerations for the MIRT AI system.

This module provides backward compatibility aliases to the new state_machine module.
For new code, import directly from src.core.state_machine.

Migration guide:
    OLD: from src.core.constants import AgentState
    NEW: from src.core.state_machine import State
"""

from __future__ import annotations

from enum import Enum

# =============================================================================
# IMPORT FROM NEW STATE MACHINE (Single Source of Truth)
# =============================================================================
from src.core.state_machine import (
    State,
)


# =============================================================================
# BACKWARD COMPATIBILITY ALIASES
# =============================================================================

# AgentState is now State - alias for backward compatibility
AgentState = State


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


class DBTable:
    """Database table names constants."""

    USERS = "mirt_users"
    MESSAGES = "mirt_messages"
    SESSIONS = "agent_sessions"
    LLM_USAGE = "llm_usage"
    
    # Memory System (Titans-like)
    PROFILES = "mirt_profiles"
    MEMORIES = "mirt_memories"
    MEMORY_SUMMARIES = "mirt_memory_summaries"


# =============================================================================
# DEFAULT VALUES
# =============================================================================
DEFAULT_MATCH_COUNT = 5
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY = 0.35
MAX_RESPONSE_CHARS = 900
