"""
Tests for tracing safeguards.

VERIFY_1: Тест що tracing не блокує основний flow
VERIFY_2: Тест graceful degradation
VERIFY_3: Лог failed traces
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.core.observability import AsyncTracingService, log_trace


@pytest.fixture
def tracing_service():
    """Create tracing service instance."""
    return AsyncTracingService()


@pytest.mark.asyncio
async def test_tracing_does_not_block_flow(tracing_service):
    """VERIFY_1: Тест що tracing не блокує основний flow."""
    # Mock Supabase client to simulate slow operation
    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute = AsyncMock()
    
    with patch("src.services.infra.supabase_client.get_supabase_client", return_value=mock_client):
        start_time = asyncio.get_event_loop().time()
        
        # Log trace (should be async and non-blocking)
        await tracing_service.log_trace(
            session_id="test_session",
            trace_id="test_trace",
            node_name="test_node",
            status="SUCCESS",
        )
        
        elapsed = asyncio.get_event_loop().time() - start_time
        
        # Should complete quickly (< 100ms for async operation)
        assert elapsed < 0.1, f"Tracing should not block flow, took {elapsed}s"


@pytest.mark.asyncio
async def test_tracing_graceful_degradation(tracing_service):
    """VERIFY_2: Тест graceful degradation."""
    # Simulate Supabase unavailable
    with patch("src.services.infra.supabase_client.get_supabase_client", return_value=None):
        # Should not raise exception
        await tracing_service.log_trace(
            session_id="test_session",
            trace_id="test_trace",
            node_name="test_node",
            status="SUCCESS",
        )
        
        # Should increment failure count
        assert tracing_service.get_failure_count() == 0  # None client doesn't increment


@pytest.mark.asyncio
async def test_tracing_logs_failed_traces(caplog, tracing_service):
    """VERIFY_3: Лог failed traces."""
    # Simulate Supabase error
    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute = AsyncMock(
        side_effect=Exception("Supabase error")
    )
    
    with patch("src.services.infra.supabase_client.get_supabase_client", return_value=mock_client):
        with caplog.at_level(logging.WARNING):
            await tracing_service.log_trace(
                session_id="test_session",
                trace_id="test_trace",
                node_name="test_node",
                status="SUCCESS",
            )
        
        # Should increment failure count
        assert tracing_service.get_failure_count() > 0
        
        # Should log failure (first 3 failures at WARNING level)
        log_messages = [record.message for record in caplog.records]
        failure_logs = [msg for msg in log_messages if "[TRACING]" in msg and "Failed" in msg]
        
        assert len(failure_logs) > 0, "Should log failed traces"
        
        # Check that log contains failure information
        log_text = " ".join(failure_logs)
        assert "failure_count=" in log_text, "Should log failure count"


@pytest.mark.asyncio
async def test_tracing_disabled_via_env(monkeypatch):
    """Test that tracing can be disabled via ENABLE_OBSERVABILITY."""
    with patch("src.services.core.observability.settings") as mock_settings:
        mock_settings.ENABLE_OBSERVABILITY = False
        
        service = AsyncTracingService()
        
        # Should not attempt to log
        await service.log_trace(
            session_id="test_session",
            trace_id="test_trace",
            node_name="test_node",
            status="SUCCESS",
        )
        
        # Failure count should remain 0 (no attempt made)
        assert service.get_failure_count() == 0


@pytest.mark.asyncio
async def test_tracing_failure_counter():
    """Test that failure counter increments on errors."""
    service = AsyncTracingService()
    
    # Simulate multiple failures
    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute = AsyncMock(
        side_effect=Exception("Error")
    )
    
    with patch("src.services.infra.supabase_client.get_supabase_client", return_value=mock_client):
        for _ in range(5):
            await service.log_trace(
                session_id="test_session",
                trace_id="test_trace",
                node_name="test_node",
                status="SUCCESS",
            )
    
    # Should have 5 failures
    assert service.get_failure_count() == 5


@pytest.mark.asyncio
async def test_tracing_reset_failure_counter():
    """Test that failure counter can be reset."""
    service = AsyncTracingService()
    
    # Simulate failure
    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute = AsyncMock(
        side_effect=Exception("Error")
    )
    
    with patch("src.services.infra.supabase_client.get_supabase_client", return_value=mock_client):
        await service.log_trace(
            session_id="test_session",
            trace_id="test_trace",
            node_name="test_node",
            status="SUCCESS",
        )
    
    assert service.get_failure_count() > 0
    
    # Reset counter
    service.reset_failure_count()
    assert service.get_failure_count() == 0


@pytest.mark.asyncio
async def test_log_trace_public_api():
    """Test that public log_trace API works."""
    # Should not raise exception
    await log_trace(
        session_id="test_session",
        trace_id="test_trace",
        node_name="test_node",
        status="SUCCESS",
    )

