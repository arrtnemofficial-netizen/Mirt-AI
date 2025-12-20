import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_prepare_payment_calculates_total_correctly():
    from src.agents.langgraph.nodes.payment import _prepare_payment_and_interrupt
    from src.agents.pydantic.models import PaymentResponse
    
    # Arrange
    state = {
        "selected_products": [
            {"name": "Item 1", "price": 100},
            {"name": "Item 2", "price": 200}
        ],
        "messages": [{"role": "user", "content": "ok"}],
        "metadata": {"session_id": "sess_1"}
    }
    
    # We patch the external dependencies that cause side effects
    # but we DO NOT patch the core logic function _prepare_payment_and_interrupt itself
    with patch("src.agents.langgraph.nodes.payment.run_payment", new_callable=AsyncMock) as mock_agent, \
         patch("src.agents.langgraph.nodes.payment.interrupt") as mock_interrupt, \
         patch("src.agents.langgraph.nodes.payment.log_agent_step"), \
         patch("src.agents.langgraph.nodes.payment.track_metric"), \
         patch("src.agents.langgraph.nodes.payment.CatalogService"), \
         patch("src.agents.langgraph.nodes.payment.create_deps_from_state", return_value=MagicMock()), \
         patch("src.agents.langgraph.nodes.payment.settings") as mock_settings:
            
        mock_settings.ENABLE_PAYMENT_HITL = True
        mock_settings.ENABLE_CRM_INTEGRATION = False
        
        # CONTRACT TESTING: Use real Pydantic model for mock return
        # This guarantees that if PaymentResponse schema changes, this test will break (good!)
        mock_agent.return_value = PaymentResponse(
            reply_to_user="Mock Reply",
            missing_fields=[],
            order_ready=True
        )
        
        # Act
        await _prepare_payment_and_interrupt(state, None, "sess_1")
        
        # Assert
        # Verify interrupt was called with correct data (Real Logic Verification)
        assert mock_interrupt.called, "Interrupt should be called"
        
        args, _ = mock_interrupt.call_args
        approval_request = args[0]
        
        # This asserts that the LOGIC inside _prepare_payment_and_interrupt 
        # correctly summed the prices from the state
        assert approval_request["total_price"] == 300, "Should sum prices 100+200"
        assert approval_request["type"] == "payment_confirmation"
        assert approval_request["message"] == "Підтвердіть оплату для цього замовлення"
