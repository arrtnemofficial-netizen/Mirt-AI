import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
from src.services.observability import AsyncTracingService

@pytest.fixture
def mock_supabase():
    with patch("src.services.supabase_client.get_supabase_client") as mock:
        client = MagicMock()
        # Create proper mock chain for table().insert().execute()
        insert_mock = MagicMock()
        insert_mock.execute = AsyncMock()
        client.table.return_value.insert.return_value = insert_mock
        mock.return_value = client
        yield client

@pytest.mark.asyncio
async def test_log_trace_success(mock_supabase):
    service = AsyncTracingService()
    service._enabled = True  # Enable the service for testing
    
    await service.log_trace(
        session_id="sess_123",
        trace_id="trace_abc",
        node_name="test_node",
        status="SUCCESS",
        state_name="STATE_1",
        latency_ms=100.5
    )
    
    # Verify insert called with correct payload (table is llm_traces)
    mock_supabase.table.assert_called_with("llm_traces")
    mock_supabase.table().insert.assert_called_once()
    
    call_args = mock_supabase.table().insert.call_args[0][0]
    assert call_args["session_id"] == "sess_123"
    # trace_id is normalized to a UUID string
    uuid.UUID(call_args["trace_id"])
    assert call_args["status"] == "SUCCESS"
    assert call_args["latency_ms"] == 100.5
    assert "created_at" in call_args

@pytest.mark.asyncio
async def test_log_trace_error(mock_supabase):
    service = AsyncTracingService()
    service._enabled = True  # Enable the service for testing
    
    await service.log_trace(
        session_id="sess_123",
        trace_id="trace_abc",
        node_name="validation",
        status="ERROR",
        error_category="BUSINESS",
        error_message="Price too low"
    )
    
    call_args = mock_supabase.table().insert.call_args[0][0]
    assert call_args["status"] == "ERROR"
    assert call_args["error_category"] == "BUSINESS"
    assert call_args["error_message"] == "Price too low"
