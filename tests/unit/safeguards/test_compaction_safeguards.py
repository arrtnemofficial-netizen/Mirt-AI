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
    assert message_content == "<base64_stripped>"


def test_compaction_reduces_payload_size():
    """Test that compaction reduces payload size for large payloads (>100KB)."""
    # Create a large checkpoint (>100KB)
    large_messages = [
        {"role": "user", "content": "A" * 1000} for _ in range(150)
    ]
    
    # Add large metadata
    large_metadata = {
        "step_history": [{"step": i, "data": "X" * 5000} for i in range(50)],
        "debug_info": {"trace": "Y" * 10000},
        "trace_id": "Z" * 1000,
    }
    
    # Add large agent_response
    large_agent_response = {
        "response_text": "B" * 5000,
        "deliberation": {"reasoning": "C" * 10000},
        "debug_info": {"raw": "D" * 5000},
    }
    
    checkpoint = {
        "channel_values": {
            "messages": large_messages,
            "metadata": large_metadata,
            "agent_response": large_agent_response,
            "selected_products": [{"id": 1, "name": "Product 1"}],
        }
    }
    
    compacted = _compact_payload(checkpoint.copy())
    
    # Calculate sizes
    import json
    try:
        import orjson
        size_before = len(orjson.dumps(checkpoint))
        size_after = len(orjson.dumps(compacted))
    except ImportError:
        size_before = len(json.dumps(checkpoint, default=str))
        size_after = len(json.dumps(compacted, default=str))
    
    # Should reduce size significantly (ratio < 0.7 for >100KB)
    if size_before > 100 * 1024:  # >100KB
        ratio = size_after / size_before
        assert ratio < 0.7, f"Compaction ratio {ratio:.2f} should be < 0.7 for large payloads"
    
    # Critical fields should be preserved
    assert "selected_products" in compacted["channel_values"]
    assert compacted["channel_values"]["selected_products"] == [{"id": 1, "name": "Product 1"}]


def test_compaction_truncates_metadata():
    """Test that metadata step_history is truncated to last 10 entries."""
    checkpoint = {
        "channel_values": {
            "messages": [],
            "metadata": {
                "step_history": [{"step": i} for i in range(50)],
                "other_data": "preserved",
            },
            "selected_products": [],
        }
    }
    
    compacted = _compact_payload(checkpoint.copy())
    
    cv = compacted["channel_values"]
    assert "metadata" in cv
    assert "step_history" in cv["metadata"]
    
    # Should be truncated to last 10 entries
    assert len(cv["metadata"]["step_history"]) == 10
    assert cv["metadata"]["step_history"][0]["step"] == 40  # Last 10: 40-49
    assert cv["metadata"]["step_history"][-1]["step"] == 49
    
    # Other metadata should be preserved
    assert cv["metadata"]["other_data"] == "preserved"


def test_compaction_removes_debug_info_for_large_payloads():
    """Test that debug_info is removed for large payloads."""
    # Create a large checkpoint (>100KB)
    large_messages = [
        {"role": "user", "content": "A" * 2000} for _ in range(100)
    ]
    
    checkpoint = {
        "channel_values": {
            "messages": large_messages,
            "metadata": {
                "debug_info": {"trace": "X" * 10000},
                "trace_id": "Y" * 1000,
            },
            "agent_response": {
                "deliberation": {"reasoning": "Z" * 10000},
                "debug_info": {"raw": "W" * 5000},
            },
            "selected_products": [],
        }
    }
    
    compacted = _compact_payload(checkpoint.copy())
    
    cv = compacted["channel_values"]
    
    # Debug info should be removed for large payloads
    if "metadata" in cv:
        assert "debug_info" not in cv["metadata"]
        assert "trace_id" not in cv["metadata"]
    
    if "agent_response" in cv:
        assert "deliberation" not in cv["agent_response"]
        assert "debug_info" not in cv["agent_response"]


def test_adaptive_compaction_reduces_limits():
    """Test that adaptive compaction reduces max_messages and max_chars for large payloads."""
    # Create a large checkpoint (>100KB)
    large_messages = [
        {"role": "user", "content": "A" * 5000} for _ in range(150)
    ]
    
    checkpoint = {
        "channel_values": {
            "messages": large_messages,
            "selected_products": [],
        }
    }
    
    # Use default max_messages=200, max_chars=4000
    compacted = _compact_payload(checkpoint.copy(), max_messages=200, max_chars=4000)
    
    cv = compacted["channel_values"]
    messages = cv["messages"]
    
    # For large payloads, adaptive compaction should reduce to 100 messages max
    # But we start with 150, so should keep 100 (not 200)
    assert len(messages) == 100
    
    # Messages should be truncated to 2000 chars (not 4000)
    for msg in messages:
        if isinstance(msg.get("content"), str):
            assert len(msg["content"]) <= 2020  # 2000 + "... [TRUNCATED]"

