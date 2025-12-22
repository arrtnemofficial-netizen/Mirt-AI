"""
Tests for checkpoint compaction safeguards.

VERIFY_1: Тест що критичні поля не стискаються
VERIFY_2: Тест що зберігаються останні повідомлення
VERIFY_3: Лог розміру до/після
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.agents.langgraph.checkpointer import _compact_payload


@pytest.fixture
def sample_checkpoint():
    """Create a sample checkpoint with critical fields and messages."""
    return {
        "channel_values": {
            "messages": [
                {"role": "user", "content": f"Message {i}"} for i in range(250)
            ],
            "selected_products": [{"id": 1, "name": "Product 1", "price": 100.0}],
            "customer_name": "Іван Іванов",
            "customer_phone": "+380501234567",
            "customer_city": "Київ",
            "customer_nova_poshta": "1",
            "current_state": "STATE_3_SIZE_COLOR",
        }
    }


def test_compaction_preserves_critical_fields(sample_checkpoint):
    """VERIFY_1: Тест що критичні поля не стискаються."""
    compacted = _compact_payload(sample_checkpoint.copy())
    
    cv = compacted["channel_values"]
    
    # Critical fields must be preserved
    assert "selected_products" in cv
    assert cv["selected_products"] == [{"id": 1, "name": "Product 1", "price": 100.0}]
    
    assert "customer_name" in cv
    assert cv["customer_name"] == "Іван Іванов"
    
    assert "customer_phone" in cv
    assert cv["customer_phone"] == "+380501234567"
    
    assert "customer_city" in cv
    assert cv["customer_city"] == "Київ"
    
    assert "customer_nova_poshta" in cv
    assert cv["customer_nova_poshta"] == "1"
    
    assert "current_state" in cv
    assert cv["current_state"] == "STATE_3_SIZE_COLOR"


def test_compaction_preserves_tail(sample_checkpoint):
    """VERIFY_2: Тест що зберігаються останні повідомлення."""
    compacted = _compact_payload(sample_checkpoint.copy())
    
    cv = compacted["channel_values"]
    messages = cv["messages"]
    
    # Should keep last 200 messages (not first 200)
    assert len(messages) == 200
    
    # First message should be "Message 50" (250 - 200 = 50)
    assert messages[0]["content"] == "Message 50"
    
    # Last message should be "Message 249"
    assert messages[-1]["content"] == "Message 249"


def test_compaction_logs_size(caplog, sample_checkpoint):
    """VERIFY_3: Лог розміру до/після."""
    with caplog.at_level(logging.INFO):
        compacted = _compact_payload(sample_checkpoint.copy())
    
    # Check that log contains size information
    log_messages = [record.message for record in caplog.records]
    compaction_logs = [msg for msg in log_messages if "[COMPACTION]" in msg]
    
    assert len(compaction_logs) > 0
    
    # Check that log contains size_before and size_after
    log_text = " ".join(compaction_logs)
    assert "size_before=" in log_text
    assert "size_after=" in log_text
    assert "ratio=" in log_text
    assert "messages_before=" in log_text
    assert "messages_after=" in log_text


def test_compaction_disabled_via_env(monkeypatch, sample_checkpoint):
    """Test that compaction can be disabled via COMPACTION_ENABLED env var."""
    # Mock settings to disable compaction
    # get_settings is imported inside _compact_payload, so we patch it at the source
    mock_settings = MagicMock()
    mock_settings.COMPACTION_ENABLED = False
    
    with patch("src.conf.config.get_settings", return_value=mock_settings):
        compacted = _compact_payload(sample_checkpoint.copy())
        
        # Should return unchanged checkpoint (compaction disabled)
        assert len(compacted["channel_values"]["messages"]) == 250


def test_compaction_truncates_long_messages():
    """Test that very long messages are truncated."""
    checkpoint = {
        "channel_values": {
            "messages": [
                {"role": "user", "content": "A" * 5000}  # Very long message
            ],
            "selected_products": [],
        }
    }
    
    compacted = _compact_payload(checkpoint)
    
    cv = compacted["channel_values"]
    message_content = cv["messages"][0]["content"]
    
    # Should be truncated to max_chars (4000) + "... [TRUNCATED]"
    assert len(message_content) <= 4020  # 4000 + len("... [TRUNCATED]")
    assert "... [TRUNCATED]" in message_content


def test_compaction_removes_base64():
    """Test that base64 image data is removed."""
    checkpoint = {
        "channel_values": {
            "messages": [
                {
                    "role": "user",
                    "content": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                }
            ],
            "selected_products": [],
        }
    }
    
    compacted = _compact_payload(checkpoint)
    
    cv = compacted["channel_values"]
    message_content = cv["messages"][0]["content"]
    
    # Should be replaced with placeholder
    assert message_content == "[IMAGE DATA REMOVED]"

