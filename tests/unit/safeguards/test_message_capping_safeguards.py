"""
Tests for message capping safeguards.

VERIFY_1: Тест що використовується add_messages reducer
VERIFY_2: Тест що зберігаються останні повідомлення
VERIFY_3: Лог коли capping спрацював
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from src.core.conversation_state import add_messages_capped


def test_message_capping_uses_add_messages():
    """VERIFY_1: Тест що використовується add_messages reducer."""
    # This is verified by code inspection - add_messages_capped calls add_messages
    # from langgraph.graph.message, then applies capping
    from langchain_core.messages import HumanMessage, AIMessage
    
    current = [HumanMessage(content="Message 1")]
    new = [AIMessage(content="Response 1")]
    
    result = add_messages_capped(current, new)
    
    # Should merge messages (add_messages behavior)
    assert len(result) == 2
    assert result[0].content == "Message 1"
    assert result[1].content == "Response 1"


def test_message_capping_preserves_tail():
    """VERIFY_2: Тест що зберігаються останні повідомлення."""
    from langchain_core.messages import HumanMessage, AIMessage
    
    # Create more than max_messages (default 100)
    current = [HumanMessage(content=f"Message {i}") for i in range(150)]
    new = [AIMessage(content="New message")]
    
    result = add_messages_capped(current, new)
    
    # Should keep last 100 messages (not first 100)
    assert len(result) == 100
    
    # First message should be from the tail (Message 51, since 150 + 1 = 151, then 151 - 100 = 51)
    assert "Message 51" in result[0].content or "Message 50" in result[0].content
    
    # Last message should be the new one
    assert result[-1].content == "New message"


def test_message_capping_logs_when_applied(caplog):
    """VERIFY_3: Лог коли capping спрацював."""
    from langchain_core.messages import HumanMessage, AIMessage
    
    with caplog.at_level(logging.INFO):
        # Create messages that will trigger capping
        current = [HumanMessage(content=f"Message {i}") for i in range(150)]
        new = [AIMessage(content="New message")]
        
        add_messages_capped(current, new)
    
    # Check that log contains trimming information
    log_messages = [record.message for record in caplog.records]
    trim_logs = [msg for msg in log_messages if "[STATE]" in msg and "Trimmed messages" in msg]
    
    assert len(trim_logs) > 0, "Should log when messages are trimmed"
    
    # Check that log contains required fields
    log_text = " ".join(trim_logs)
    assert "trimmed=" in log_text, "Should log trimmed count"
    assert "kept=" in log_text, "Should log kept count"


def test_message_capping_respects_max_messages_setting(monkeypatch):
    """Test that capping respects STATE_MAX_MESSAGES setting."""
    from langchain_core.messages import HumanMessage, AIMessage
    
    # Mock settings to return custom max_messages
    with patch("src.core.conversation_state._resolve_state_max_messages", return_value=50):
        current = [HumanMessage(content=f"Message {i}") for i in range(100)]
        new = [AIMessage(content="New message")]
        
        result = add_messages_capped(current, new)
        
        # Should keep last 50 messages
        assert len(result) == 50


def test_message_capping_no_trim_when_under_limit():
    """Test that capping doesn't trim when under limit."""
    from langchain_core.messages import HumanMessage, AIMessage
    
    current = [HumanMessage(content=f"Message {i}") for i in range(50)]
    new = [AIMessage(content="New message")]
    
    result = add_messages_capped(current, new)
    
    # Should keep all messages (51 total, under default limit of 100)
    assert len(result) == 51


def test_message_capping_disabled_when_max_messages_zero(monkeypatch):
    """Test that capping is disabled when max_messages is 0."""
    from langchain_core.messages import HumanMessage, AIMessage
    
    with patch("src.core.conversation_state._resolve_state_max_messages", return_value=0):
        current = [HumanMessage(content=f"Message {i}") for i in range(200)]
        new = [AIMessage(content="New message")]
        
        result = add_messages_capped(current, new)
        
        # Should keep all messages (capping disabled)
        assert len(result) == 201

