"""
History Trimmer - Prevent LLM context overflow.
=================================================

Trims message history to a configurable maximum length,
keeping the most recent messages and important context.

Why this matters:
- LLM context windows have limits (8K-128K tokens)
- Long history = slow responses + high cost
- Very old messages rarely relevant to current turn
"""

from __future__ import annotations

import logging
from typing import Any

from src.conf.config import settings


logger = logging.getLogger(__name__)


def trim_message_history(
    messages: list[dict[str, Any]],
    max_messages: int | None = None,
    preserve_system: bool = True,
) -> list[dict[str, Any]]:
    """
    Trim message history to prevent context overflow.
    
    Args:
        messages: Full message history
        max_messages: Maximum messages to keep (uses config if None)
        preserve_system: Keep system messages at the start
        
    Returns:
        Trimmed message list with most recent messages
        
    Strategy:
        1. Keep all system messages (if preserve_system=True)
        2. Keep the last N user/assistant messages
        3. Log when trimming occurs
    """
    if max_messages is None:
        max_messages = settings.LLM_MAX_HISTORY_MESSAGES
    
    # Disabled if max_messages is 0
    if max_messages <= 0:
        return messages
    
    # No trimming needed
    if len(messages) <= max_messages:
        return messages
    
    # Separate system messages from conversation
    system_messages = []
    conversation_messages = []
    
    for msg in messages:
        role = _get_message_role(msg)
        if role == "system" and preserve_system:
            system_messages.append(msg)
        else:
            conversation_messages.append(msg)
    
    # Calculate how many conversation messages to keep
    # Reserve space for system messages
    available_slots = max_messages - len(system_messages)
    
    if available_slots <= 0:
        # Extreme case: too many system messages
        logger.warning(
            "Too many system messages (%d) for max_messages=%d",
            len(system_messages),
            max_messages,
        )
        return system_messages[:max_messages]
    
    # Trim conversation to last N messages
    trimmed_conversation = conversation_messages[-available_slots:]
    
    trimmed_count = len(conversation_messages) - len(trimmed_conversation)
    if trimmed_count > 0:
        logger.info(
            "📝 Trimmed %d old messages (keeping %d system + %d conversation)",
            trimmed_count,
            len(system_messages),
            len(trimmed_conversation),
        )
        
        # Track metric
        from src.services.observability import track_metric
        track_metric("history_messages_trimmed", trimmed_count)
    
    return system_messages + trimmed_conversation


def _get_message_role(msg: Any) -> str:
    """Extract role from message (handles dict and LangChain objects)."""
    if isinstance(msg, dict):
        return msg.get("role", "")
    
    # LangChain Message objects
    msg_type = getattr(msg, "type", "")
    if msg_type == "human":
        return "user"
    if msg_type == "ai":
        return "assistant"
    if msg_type == "system":
        return "system"
    
    return msg_type


def estimate_token_count(messages: list[dict[str, Any]]) -> int:
    """
    Rough estimate of token count for message list.
    
    Uses simple heuristic: ~4 characters per token.
    Not accurate but good enough for trimming decisions.
    """
    total_chars = 0
    
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content", "")
        else:
            content = getattr(msg, "content", "")
        
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            # Multimodal content
            for item in content:
                if isinstance(item, dict):
                    total_chars += len(item.get("text", ""))
    
    return total_chars // 4


def should_trim(
    messages: list[dict[str, Any]],
    max_messages: int | None = None,
    max_tokens: int = 100000,
) -> bool:
    """
    Check if trimming is needed.
    
    Returns True if:
    - Message count exceeds max_messages
    - Estimated tokens exceed max_tokens
    """
    if max_messages is None:
        max_messages = settings.LLM_MAX_HISTORY_MESSAGES
    
    if len(messages) > max_messages:
        return True
    
    if estimate_token_count(messages) > max_tokens:
        return True
    
    return False
