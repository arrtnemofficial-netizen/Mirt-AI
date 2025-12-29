"""
Agent-specific exception hierarchy.

This module provides specific exception types for agent errors,
allowing better error handling and logging.
"""


class AgentError(Exception):
    """Base exception for agent errors."""
    pass


class AgentTimeoutError(AgentError):
    """Agent execution timeout."""
    pass


class AgentValidationError(AgentError):
    """Agent input validation error."""
    pass


class AgentLLMError(AgentError):
    """LLM API error."""
    pass


class AgentNetworkError(AgentError):
    """Network error during agent execution."""
    pass

