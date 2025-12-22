"""
Tests for invoke_with_retry safeguards.

VERIFY_1: Тест що payment НЕ retry
VERIFY_2: Тест що order creation НЕ retry
VERIFY_3: Лог причини retry
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.langgraph.graph import invoke_with_retry


@pytest.fixture
def mock_graph():
    """Create a mock graph."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock()
    return graph


@pytest.mark.asyncio
async def test_retry_blacklist_payment(mock_graph):
    """VERIFY_1: Тест що payment НЕ retry."""
    state = {
        "session_id": "test_session",
        "current_state": "STATE_5_PAYMENT_DELIVERY",
        "dialog_phase": "payment",
        "current_node": "payment",
    }
    
    # Simulate error
    mock_graph.ainvoke.side_effect = Exception("Payment error")
    
    result = await invoke_with_retry(state, "test_session", graph=mock_graph)
    
    # Should invoke only once (no retry)
    assert mock_graph.ainvoke.call_count == 1
    
    # Should escalate immediately
    assert result["should_escalate"] is True
    assert "Unsafe operation failed" in result["escalation_reason"]


@pytest.mark.asyncio
async def test_retry_blacklist_order_creation(mock_graph):
    """VERIFY_2: Тест що order creation НЕ retry."""
    state = {
        "session_id": "test_session",
        "current_state": "STATE_5_PAYMENT_DELIVERY",
        "current_node": "order_creation",
    }
    
    # Simulate error
    mock_graph.ainvoke.side_effect = Exception("Order creation error")
    
    result = await invoke_with_retry(state, "test_session", graph=mock_graph)
    
    # Should invoke only once (no retry)
    assert mock_graph.ainvoke.call_count == 1
    
    # Should escalate immediately
    assert result["should_escalate"] is True
    assert "Unsafe operation failed" in result["escalation_reason"]


@pytest.mark.asyncio
async def test_retry_detailed_logging(caplog, mock_graph):
    """VERIFY_3: Лог причини retry."""
    state = {
        "session_id": "test_session",
        "current_state": "STATE_1_DISCOVERY",
        "current_node": "agent",
    }
    
    # Simulate error that will trigger retry
    mock_graph.ainvoke.side_effect = TimeoutError("Graph timeout")
    
    with caplog.at_level(logging.WARNING):
        await invoke_with_retry(state, "test_session", graph=mock_graph, max_attempts=2)
    
    # Check that log contains detailed information
    log_messages = [record.message for record in caplog.records]
    retry_logs = [msg for msg in log_messages if "[RETRY]" in msg]
    
    assert len(retry_logs) > 0, "Should log retry attempts"
    
    # Check that log contains required fields
    log_text = " ".join(retry_logs)
    assert "error_type=" in log_text, "Should log error_type"
    assert "error_message=" in log_text, "Should log error_message"
    assert "node_name=" in log_text, "Should log node_name"
    assert "attempt=" in log_text, "Should log attempt number"
    assert "retry_delay=" in log_text, "Should log retry delay"


@pytest.mark.asyncio
async def test_retry_max_delay_cap(mock_graph):
    """Test that retry delay is capped at 30s."""
    state = {
        "session_id": "test_session",
        "current_state": "STATE_1_DISCOVERY",
        "current_node": "agent",
    }
    
    # Simulate error
    mock_graph.ainvoke.side_effect = Exception("Error")
    
    start_time = asyncio.get_event_loop().time()
    await invoke_with_retry(state, "test_session", graph=mock_graph, max_attempts=3)
    elapsed = asyncio.get_event_loop().time() - start_time
    
    # With max_attempts=3, delays should be: 2s, 4s (capped at 30s)
    # Total should be less than 30s
    assert elapsed < 35, f"Total retry time should be < 35s, got {elapsed}s"


@pytest.mark.asyncio
async def test_retry_allows_safe_operations(mock_graph):
    """Test that safe operations (non-payment/order) can retry."""
    state = {
        "session_id": "test_session",
        "current_state": "STATE_1_DISCOVERY",
        "current_node": "agent",
    }
    
    # First call fails, second succeeds
    mock_graph.ainvoke.side_effect = [Exception("Network error"), {"status": "ok"}]
    
    result = await invoke_with_retry(state, "test_session", graph=mock_graph, max_attempts=3)
    
    # Should have retried (called twice)
    assert mock_graph.ainvoke.call_count == 2
    
    # Should return successful result
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_retry_returns_error_state_after_max_attempts(mock_graph):
    """Test that retry returns error state after all attempts fail."""
    state = {
        "session_id": "test_session",
        "current_state": "STATE_1_DISCOVERY",
        "current_node": "agent",
    }
    
    # All attempts fail
    mock_graph.ainvoke.side_effect = Exception("Persistent error")
    
    result = await invoke_with_retry(state, "test_session", graph=mock_graph, max_attempts=3)
    
    # Should have tried 3 times
    assert mock_graph.ainvoke.call_count == 3
    
    # Should return error state
    assert result["should_escalate"] is True
    assert "System error after 3 attempts" in result["escalation_reason"]
    assert "last_error" in result

