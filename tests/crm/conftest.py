"""
CRM Test Configuration and Fixtures
====================================

Shared fixtures and utilities for CRM integration tests.
Provides proper mock implementations and test data.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any, List
import json
from datetime import datetime, timezone
import sys
from pathlib import Path

# Add project root to path
root = Path(__file__).resolve().parents[2]
project_root = str(root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import actual functions from codebase
from src.agents.langgraph.state import create_initial_state
from src.agents.langgraph.graph import invoke_graph, invoke_with_retry, get_production_graph
from src.agents.langgraph.nodes.crm_error import crm_error_node
from src.agents.langgraph.nodes.payment import payment_node
from src.agents.langgraph.nodes.upsell import upsell_node
from src.integrations.crm.crmservice import CRMService
from src.integrations.crm.error_handler import CRMErrorHandler


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_crm_service():
    """Mock CRM service for testing."""
    service = Mock(spec=CRMService)
    service.create_order = AsyncMock()
    service.get_order_status = AsyncMock()
    service.check_existing_order = AsyncMock(return_value=False)
    service.update_order_status = AsyncMock()
    return service


@pytest.fixture
def mock_error_handler():
    """Mock CRM error handler."""
    handler = Mock(spec=CRMErrorHandler)
    handler.categorize_error = Mock()
    handler.get_recovery_message = Mock()
    handler.should_escalate = Mock(return_value=False)
    return handler


@pytest.fixture
def base_crm_state():
    """Base state for CRM testing."""
    return create_initial_state(
        session_id="test_crm_session_123",
        messages=[
            {"role": "user", "content": "Привіт! Я хочу купити сукню"},
            {"role": "assistant", "content": "Доброго дня! Я допоможу вам з вибором."}
        ],
        metadata={
            "channel": "instagram",
            "user_id": "user_crm_test_456",
            "language": "uk"
        }
    )


@pytest.fixture
def payment_ready_state():
    """State ready for payment and CRM integration."""
    state = create_initial_state(
        session_id="crm_payment_test_session",
        messages=[
            {"role": "user", "content": "Я беру цю сукню"},
            {"role": "assistant", "content": "Чудовий вибір! Оформлюємо замовлення..."}
        ],
        metadata={
            "channel": "instagram",
            "user_id": "user_payment_test_789"
        }
    )
    
    # Add CRM-relevant data
    state.update({
        "current_state": "STATE_5_PAYMENT_DELIVERY",
        "dialog_phase": "PAYMENT_APPROVAL",
        "selected_products": [
            {
                "id": 1,
                "name": "Сукня літня",
                "price": 899,
                "size": "M",
                "color": "блакитний",
                "photo_url": "https://cdn.example.com/dress.jpg",
                "quantity": 1
            }
        ],
        "customer_data": {
            "name": "Олена Ковальчук",
            "phone": "+380501234567",
            "delivery_address": "м. Київ, вул. Хрещатик, 1, кв. 15",
            "email": "olena@example.com"
        },
        "payment_approved": True,
        "human_approved": True,
        "payment_method": "card",
        "step_number": 15,
        "retry_count": 0,
        "max_retries": 3
    })
    
    return state


@pytest.fixture
def crm_error_state():
    """State in CRM error handling."""
    state = create_initial_state(
        session_id="crm_error_test_session",
        messages=[
            {"role": "user", "content": "Проблема з замовленням"},
            {"role": "assistant", "content": "Виправлю проблему..."}
        ],
        metadata={"channel": "instagram"}
    )
    
    state.update({
        "current_state": "CRM_ERROR_HANDLING",
        "dialog_phase": "CRM_ERROR_HANDLING",
        "step_number": 16,
        "retry_count": 1,
        "max_retries": 3,
        "selected_products": [
            {
                "id": 1,
                "name": "Сукня літня",
                "price": 899,
                "size": "M",
                "color": "блакитний"
            }
        ],
        "customer_data": {
            "name": "Анна Петренко",
            "phone": "+380509876543",
            "delivery_address": "м. Львів, вул. Свободи, 10"
        },
        "payment_approved": True,
        "crm_order_result": {
            "status": "failed",
            "error": "network_error",
            "error_details": "Connection timeout to CRM API"
        },
        "crm_error_type": "network_error",
        "crm_retry_count": 1,
        "last_error": "CRM network_error: Connection timeout"
    })
    
    return state


@pytest.fixture
def sample_webhook_payload():
    """Sample webhook payload structure."""
    return {
        "event_id": "evt_123456789",
        "event_type": "order.status.changed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "order_id": "CRM-98765",
            "external_id": "ext-order-12345",
            "status": "created",
            "previous_status": "queued",
            "metadata": {
                "customer_id": "cust_456",
                "total_amount": 899.00,
                "currency": "UAH"
            }
        },
        "signature": "webhook_signature_123"
    }


@pytest.fixture
def active_graph():
    """Get the active LangGraph for testing."""
    return get_production_graph()


@pytest.fixture
def crm_test_data():
    """Sample CRM test data."""
    return {
        "valid_customer": {
            "name": "Тестовий Клієнт",
            "phone": "+380501234567",
            "delivery_address": "м. Київ, вул. Тестова, 1",
            "email": "test@example.com"
        },
        "valid_products": [
            {
                "id": 1,
                "name": "Сукня літня",
                "price": 899,
                "size": "M",
                "color": "блакитний",
                "quantity": 1
            }
        ],
        "crm_responses": {
            "success": {
                "status": "created",
                "crm_order_id": "CRM-SUCCESS-123",
                "external_id": "ext-success-456",
                "task_id": "task-success-789"
            },
            "queued": {
                "status": "queued",
                "crm_order_id": None,
                "external_id": "ext-queued-456",
                "task_id": "task-queued-789"
            },
            "failed": {
                "status": "failed",
                "error": "network_error",
                "error_details": "Connection timeout"
            }
        }
    }


# Test utilities
class CRMTestHelper:
    """Helper class for CRM testing utilities."""
    
    @staticmethod
    def create_mock_crm_response(status: str, **kwargs):
        """Create mock CRM response."""
        base_response = {
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        base_response.update(kwargs)
        return base_response
    
    @staticmethod
    def create_test_state(session_id: str, **overrides):
        """Create test state with overrides."""
        state = create_initial_state(
            session_id=session_id,
            messages=[{"role": "user", "content": "Тест"}],
            metadata={"channel": "test"}
        )
        state.update(overrides)
        return state
    
    @staticmethod
    def assert_crm_state_valid(state: Dict[str, Any]):
        """Assert that CRM state is valid."""
        assert "session_id" in state
        assert "current_state" in state
        assert "dialog_phase" in state
        
        if "crm_order_result" in state and state["crm_order_result"]:
            assert "status" in state["crm_order_result"]
    
    @staticmethod
    def assert_error_state_valid(state: Dict[str, Any]):
        """Assert that error state is valid."""
        assert state.get("current_state") == "CRM_ERROR_HANDLING"
        assert state.get("dialog_phase") == "CRM_ERROR_HANDLING"
        assert "crm_order_result" in state
        assert state["crm_order_result"].get("status") == "failed"


@pytest.fixture
def crm_helper():
    """CRM test helper fixture."""
    return CRMTestHelper()


# Environment setup for tests
@pytest.fixture(autouse=True)
def setup_test_environment():
    """Setup environment variables for CRM tests."""
    import os
    
    # Set required environment variables
    test_env_vars = {
        "SNITKIX_ENABLED": "true",
        "SNITKIX_API_URL": "https://test-snitkix.example.com",
        "SNITKIX_API_KEY": "test_api_key_123",
        "CELERY_EAGER": "true",
        "REDIS_URL": "redis://localhost:6379/1"
    }
    
    original_vars = {}
    for key, value in test_env_vars.items():
        original_vars[key] = os.environ.get(key)
        os.environ[key] = value
    
    yield
    
    # Restore original environment
    for key, original_value in original_vars.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


# Mock patches for common dependencies
# @pytest.fixture(autouse=True)
# def mock_external_dependencies():
#     """Mock external dependencies for CRM tests."""
#     with patch('src.integrations.crm.crmservice.get_db_connection') as mock_db:
#         mock_conn = Mock()
#         mock_conn.execute = Mock()
#         mock_conn.commit = Mock()
#         mock_conn.close = Mock()
#         mock_db.return_value = mock_conn
#         yield mock_db


# Error scenarios for testing
@pytest.fixture
def crm_error_scenarios():
    """CRM error scenarios for testing."""
    return {
        "network_error": {
            "exception": Exception("Network timeout"),
            "error_type": "network_error",
            "expected_message": "Проблеми з зв'язком з CRM системою"
        },
        "timeout_error": {
            "exception": TimeoutError("CRM API timeout"),
            "error_type": "timeout_error", 
            "expected_message": "CRM система не відповідає"
        },
        "rate_limit_error": {
            "exception": Exception("Rate limit exceeded"),
            "error_type": "rate_limit_error",
            "expected_message": "Забагато запитів до CRM"
        },
        "crm_rejected": {
            "exception": Exception("CRM rejected order"),
            "error_type": "crm_rejected",
            "expected_message": "CRM відхилила замовлення"
        },
        "unknown_error": {
            "exception": Exception("Unknown internal error"),
            "error_type": "unknown_error",
            "expected_message": "Невідома помилка CRM"
        }
    }


# Test data generators
@pytest.fixture
def generate_test_orders():
    """Generate test order data."""
    def _generate_orders(count: int = 1):
        orders = []
        for i in range(count):
            order = {
                "session_id": f"test_session_{i}",
                "crm_order_id": f"CRM-TEST-{i}",
                "external_id": f"ext-test-{i}",
                "status": "created",
                "customer_data": json.dumps({
                    "name": f"Тестовий Клієнт {i}",
                    "phone": f"+380501234{i:03d}",
                    "delivery_address": f"м. Київ, вул. Тестова, {i}"
                }),
                "order_data": json.dumps({
                    "products": [{"id": i, "name": f"Товар {i}", "price": 100 * (i + 1)}],
                    "total": 100 * (i + 1)
                }),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            orders.append(order)
        return orders
    return _generate_orders


# Performance testing utilities
@pytest.fixture
def performance_monitor():
    """Performance monitoring for tests."""
    import time
    
    class PerformanceMonitor:
        def __init__(self):
            self.start_time = None
            self.end_time = None
        
        def start(self):
            self.start_time = time.time()
        
        def stop(self):
            self.end_time = time.time()
        
        @property
        def duration(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None
    
    return PerformanceMonitor()
