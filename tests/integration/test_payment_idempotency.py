from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.services.domain.payment.payment_crm import create_and_submit_order

@pytest.mark.asyncio
async def test_payment_idempotency_via_vision_id(monkeypatch):
    """Verify that payment_crm prevents duplicate orders using vision_result_id."""
    
    vision_id = "test-vision-uuid-123"
    session_id = "test-session"
    
    # Mock Supabase
    mock_supabase = MagicMock()
    # First call: return data (order exists)
    mock_supabase.table().select().eq().execute.return_value = MagicMock(data=[{"id": "order_existing_1"}])
    
    monkeypatch.setattr("src.services.infra.supabase_client.get_supabase_client", lambda: mock_supabase)
    
    # Mock CRM service to ensure it's NOT called
    crm_mock = AsyncMock()
    monkeypatch.setattr("src.services.domain.payment.payment_crm.get_crm_service", lambda: crm_mock)

    result = await create_and_submit_order(
        session_id=session_id,
        user_id="tg_1",
        user_nickname="user",
        metadata={"vision_result_id": vision_id},
        products=[{"name": "p1", "price": 100}],
        total_price=100.0
    )

    assert result["status"] == "success"
    assert "Duplicate blocked" in result["message"]
    assert result["order_id"] == "order_existing_1"
    
    # Ensure CRM was not called
    crm_mock.create_order_with_persistence.assert_not_called()
