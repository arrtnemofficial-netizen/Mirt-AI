"""Core domain models and utilities for MIRT AI.

This package contains the fundamental building blocks:
- constants: Enums and type-safe constants
- models: Pydantic data models (AgentResponse, Product, etc.)
- validation: Input validation utilities
- logging: Structured logging configuration
"""

from src.core.constants import (
    AgentState,
    MessageRole,
    MessageTag,
    ModerationFlag,
)
from src.core.models import (
    AgentResponse,
    DebugInfo,
    Escalation,
    Message,
    Metadata,
    Product,
)
from src.core.debug_logger import debug_log
from src.core.state_machine import EscalationLevel


__all__ = [
    # Models
    "AgentResponse",
    "DebugInfo",
    "Escalation",
    "Message",
    "Metadata",
    "Product",
    # Constants
    "AgentState",
    "EscalationLevel",
    "MessageRole",
    "MessageTag",
    "ModerationFlag",
    # Utilities
    "debug_log",
]

