"""Core domain models and utilities for MIRT AI.

This package contains the fundamental building blocks:
- constants: Enums and type-safe constants
- models: Pydantic data models (AgentResponse, Product, etc.)
- validation: Input validation utilities
- logging: Structured logging configuration
"""
from src.core.constants import (
    AgentState,
    EscalationLevel,
    EventType,
    MessageRole,
    MessageTag,
    ModerationFlag,
    ToolName,
)
from src.core.models import (
    AgentResponse,
    DebugInfo,
    Escalation,
    Message,
    Metadata,
    Product,
)

__all__ = [
    # Constants
    "AgentState",
    "EscalationLevel",
    "EventType",
    "MessageRole",
    "MessageTag",
    "ModerationFlag",
    "ToolName",
    # Models
    "AgentResponse",
    "DebugInfo",
    "Escalation",
    "Message",
    "Metadata",
    "Product",
]
