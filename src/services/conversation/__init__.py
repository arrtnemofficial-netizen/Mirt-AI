"""Conversation handling package.

This package provides centralized conversation handling with:
- ConversationHandler: Main class for message processing
- ConversationResult: Result of processing a user message
- Exception classes for error handling
- FSM guardrails for state validation
- LLM output parsing utilities

Usage:
    from src.services.conversation import ConversationHandler, ConversationResult

For advanced usage:
    from src.services.conversation.guardrails import apply_transition_guardrails
    from src.services.conversation.parser import parse_llm_output
"""

from src.services.conversation.exceptions import (
    AgentInvocationError,
    ConversationError,
    ResponseParsingError,
)
from src.services.conversation.handler import (
    ConversationHandler,
    create_conversation_handler,
)
from src.services.conversation.models import (
    ConversationResult,
    GraphRunner,
    TransitionResult,
)
from src.services.conversation.parser import parse_llm_output, validate_state_transition

# Re-export for backward compatibility
from src.services.conversation.guardrails import (
    apply_transition_guardrails,
    _apply_transition_guardrails,  # Backward compat alias
)

__all__ = [
    # Main exports
    "ConversationHandler",
    "ConversationResult",
    "create_conversation_handler",
    # Exceptions
    "ConversationError",
    "AgentInvocationError",
    "ResponseParsingError",
    # Models
    "GraphRunner",
    "TransitionResult",
    # Functions
    "parse_llm_output",
    "validate_state_transition",
    "apply_transition_guardrails",
    "_apply_transition_guardrails",
]
