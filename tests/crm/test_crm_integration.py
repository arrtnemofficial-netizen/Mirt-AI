"""
CRM INTEGRATION TEST SUITE
===========================

Тестує CRM інтеграцію з Snitkix:
- crm_error_node функціональність
- CRM error handling
- Retry/Escalation/Back flows

АВТОР: AI Test Suite Generator
ДАТА: 2024-12-08
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from langgraph.types import Command
import sys
from pathlib import Path

# Add project root to path
root = Path(__file__).resolve().parents[2]
project_root = str(root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.langgraph.state import create_initial_state
from src.agents.langgraph.nodes.crm_error import crm_error_node
from src.integrations.crm.crmservice import CRMService
from src.integrations.crm.error_handler import CRMErrorHandler


class TestCRMErrorNode:
    """Test crm_error_node functionality."""
    
    @pytest.fixture
    def crm_error_state(self):
        """CRM error state for testing."""
        state = create_initial_state(
            session_id="crm_error_test",
            messages=[{"role": "user", "content": "Повторити"}],
            metadata={"channel": "instagram"}
        )
        
        state.update({
            "current_state": "CRM_ERROR_HANDLING",
            "dialog_phase": "CRM_ERROR_HANDLING",
            "crm_order_result": {
                "status": "failed",
                "error": "network_error"
            },
            "crm_error_type": "network_error",
            "crm_retry_count": 1,
            "max_retries": 3
        })
        
        return state
    
    @pytest.mark.asyncio
    async def test_crm_error_node_returns_command(self, crm_error_state):
        """crm_error_node returns LangGraph Command."""
        state = crm_error_state.copy()
        state["user_action"] = "retry"
        
        result = await crm_error_node(state)
        
        assert isinstance(result, Command)
        assert isinstance(result.update, dict)
        assert result.goto == "crm_error"
    
    @pytest.mark.asyncio
    async def test_crm_error_retry_flow(self, crm_error_state):
        """Test retry flow in crm_error_node."""
        state = crm_error_state.copy()
        state["user_action"] = "retry"
        
        result = await crm_error_node(state)
        
        assert isinstance(result, Command)
        assert result.goto == "crm_error"
        
        # Check response contains retry message
        updated_state = {**state, **result.update}
        assert "agent_response" in updated_state
        response_str = str(updated_state["agent_response"])
        assert "проблем" in response_str.lower() or "спроб" in response_str.lower()
    
    @pytest.mark.asyncio
    async def test_crm_error_escalation_after_max_retries(self, crm_error_state):
        """Test escalation after max retries."""
        state = crm_error_state.copy()
        state["crm_retry_count"] = 3  # Max retries
        state["user_action"] = "retry"
        
        result = await crm_error_node(state)
        
        assert isinstance(result, Command)
        assert result.goto == "crm_error"
        
        # Check response contains escalation message
        updated_state = {**state, **result.update}
        response_str = str(updated_state["agent_response"])
        assert "оператор" in response_str.lower() or "передано" in response_str.lower()
    
    @pytest.mark.asyncio
    async def test_crm_error_back_flow(self, crm_error_state):
        """Test back to discovery flow.
        
        ПРИМІТКА: back flow залишається в crm_error для обробки,
        потім роутиться через master_router.
        """
        state = crm_error_state.copy()
        state["user_action"] = "back"
        
        result = await crm_error_node(state)
        
        assert isinstance(result, Command)
        # Back flow stays in crm_error for processing
        assert result.goto == "crm_error"
        
        # Check response contains back message
        updated_state = {**state, **result.update}
        response_str = str(updated_state["agent_response"])
        assert "назад" in response_str.lower() or "оформлення" in response_str.lower()
    
    @pytest.mark.asyncio
    async def test_crm_error_escalate_flow(self, crm_error_state):
        """Test explicit escalation flow."""
        state = crm_error_state.copy()
        state["user_action"] = "escalate"
        
        result = await crm_error_node(state)
        
        assert isinstance(result, Command)
        
        # Check response contains escalation message
        updated_state = {**state, **result.update}
        response_str = str(updated_state["agent_response"])
        assert "оператор" in response_str.lower() or "передано" in response_str.lower()
    
    @pytest.mark.asyncio
    async def test_crm_error_awaiting_user_choice(self, crm_error_state):
        """Test awaiting_user_choice flag is set."""
        state = crm_error_state.copy()
        state["user_action"] = "retry"
        
        result = await crm_error_node(state)
        
        updated_state = {**state, **result.update}
        assert updated_state.get("awaiting_user_choice") is True


class TestCRMErrorHandler:
    """Test CRM error handler functionality."""
    
    def test_error_handler_exists(self):
        """Test CRMErrorHandler class exists."""
        assert CRMErrorHandler is not None
    
    def test_crm_service_exists(self):
        """Test CRMService class exists."""
        assert CRMService is not None


class TestCRMStateTransitions:
    """Test CRM-related state transitions."""
    
    def test_crm_error_handling_phase_routes_correctly(self):
        """CRM_ERROR_HANDLING phase routes to crm_error."""
        from src.agents.langgraph.edges import master_router
        
        state = create_initial_state(
            session_id="crm_routing_test",
            messages=[{"role": "user", "content": "Повторити"}],
            metadata={"channel": "instagram"}
        )
        state["dialog_phase"] = "CRM_ERROR_HANDLING"
        
        result = master_router(state)
        assert result == "crm_error"


def test_crm_imports_work():
    """Test CRM imports work correctly."""
    from src.agents.langgraph.nodes.crm_error import crm_error_node
    from src.integrations.crm.crmservice import CRMService
    from src.integrations.crm.error_handler import CRMErrorHandler
    
    assert callable(crm_error_node)
    assert CRMService is not None
    assert CRMErrorHandler is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
