"""Conversation-related exceptions.

These exceptions are used by ConversationHandler for error handling
and graceful degradation.
"""

from __future__ import annotations


class ConversationError(Exception):
    """Base exception for conversation processing errors."""

    def __init__(self, message: str, session_id: str, recoverable: bool = True):
        super().__init__(message)
        self.session_id = session_id
        self.recoverable = recoverable


class AgentInvocationError(ConversationError):
    """Raised when the AI agent fails to process a message."""

    pass


class ResponseParsingError(ConversationError):
    """Raised when the agent response cannot be parsed."""

    pass
