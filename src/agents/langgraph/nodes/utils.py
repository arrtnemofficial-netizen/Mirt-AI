"""
Node Utilities - Common helpers for all nodes.
==============================================
"""

from __future__ import annotations

from typing import Any


def extract_user_message(messages: list[Any]) -> str:
    """
    Extract the latest user message from messages list.
    
    Handles both:
    - Dict format: {"role": "user", "content": "..."}
    - LangChain Message objects: HumanMessage, AIMessage, etc.
    
    The add_messages reducer in LangGraph converts dicts to Message objects,
    so we need to handle both formats.
    
    Args:
        messages: List of messages (dict or Message objects)
        
    Returns:
        Content of the latest user message, or empty string if not found
    """
    for msg in reversed(messages):
        # Handle dict format
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                return msg.get("content", "")
        else:
            # LangChain Message object (HumanMessage, AIMessage, etc.)
            # Check by type attribute or class name
            msg_type = getattr(msg, "type", None)
            class_name = msg.__class__.__name__
            
            if msg_type == "human" or class_name == "HumanMessage":
                return getattr(msg, "content", "")
    
    return ""


def extract_assistant_message(messages: list[Any]) -> str:
    """
    Extract the latest assistant message from messages list.
    
    Args:
        messages: List of messages (dict or Message objects)
        
    Returns:
        Content of the latest assistant message, or empty string if not found
    """
    for msg in reversed(messages):
        if isinstance(msg, dict):
            if msg.get("role") == "assistant":
                return msg.get("content", "")
        else:
            msg_type = getattr(msg, "type", None)
            class_name = msg.__class__.__name__
            
            if msg_type == "ai" or class_name == "AIMessage":
                return getattr(msg, "content", "")
    
    return ""
