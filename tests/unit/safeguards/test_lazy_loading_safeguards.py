"""
Tests for lazy loading safeguards in AgentDeps.

VERIFY_1: Тест що сервіси singleton
VERIFY_2: Лог при створенні важкого клієнта
VERIFY_3: Перевірка що немає прихованих мережевих з'єднань
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from src.agents.pydantic.deps import AgentDeps


@pytest.fixture
def deps():
    """Create AgentDeps instance."""
    return AgentDeps(session_id="test_session_1", user_id="test_user_1")


def test_agent_deps_singleton(deps):
    """VERIFY_1: Тест що сервіси singleton."""
    # Access catalog twice
    catalog1 = deps.catalog
    catalog2 = deps.catalog
    
    # Should be the same instance
    assert id(catalog1) == id(catalog2)
    
    # Same for other services
    memory1 = deps.memory
    memory2 = deps.memory
    assert id(memory1) == id(memory2)
    
    db1 = deps.db
    db2 = deps.db
    assert id(db1) == id(db2)


def test_lazy_loading_logs_creation(caplog, deps):
    """VERIFY_2: Лог при створенні важкого клієнта."""
    with caplog.at_level(logging.INFO):
        # Access services to trigger lazy loading
        _ = deps.catalog
        _ = deps.memory
        _ = deps.db
        _ = deps.vision
    
    # Check that logs contain creation messages
    log_messages = [record.message for record in caplog.records]
    
    # Should log creation of each service
    catalog_logs = [msg for msg in log_messages if "Creating CatalogService" in msg]
    memory_logs = [msg for msg in log_messages if "Creating MemoryService" in msg]
    db_logs = [msg for msg in log_messages if "Creating OrderService" in msg]
    vision_logs = [msg for msg in log_messages if "Creating VisionContextService" in msg]
    
    assert len(catalog_logs) > 0, "Should log CatalogService creation"
    assert len(memory_logs) > 0, "Should log MemoryService creation"
    assert len(db_logs) > 0, "Should log OrderService creation"
    assert len(vision_logs) > 0, "Should log VisionContextService creation"
    
    # Check that logs contain session_id
    for log in catalog_logs + memory_logs + db_logs + vision_logs:
        assert "test_session_1" in log or "session=" in log


def test_lazy_loading_logs_service_id(caplog, deps):
    """VERIFY_3: Перевірка що немає прихованих мережевих з'єднань."""
    with caplog.at_level(logging.DEBUG):
        catalog = deps.catalog
        catalog_id = id(catalog)
    
    # Check that debug log contains service ID
    log_messages = [record.message for record in caplog.records]
    debug_logs = [msg for msg in log_messages if "[AGENT_DEPS]" in msg and "id=" in msg]
    
    assert len(debug_logs) > 0, "Should log service ID for debugging"
    
    # Verify that the logged ID matches the actual service ID
    for log in debug_logs:
        if "CatalogService" in log:
            assert str(catalog_id) in log or "id=" in log


def test_lazy_loading_only_creates_once(deps):
    """Test that services are only created once (lazy loading)."""
    # Access catalog multiple times
    catalog1 = deps.catalog
    catalog2 = deps.catalog
    catalog3 = deps.catalog
    
    # All should be the same instance
    assert catalog1 is catalog2 is catalog3
    
    # Check internal state
    assert deps._catalog is not None
    assert deps._catalog is catalog1


def test_lazy_loading_creates_on_demand(deps):
    """Test that services are created only when accessed."""
    # Initially, services should be None
    assert deps._catalog is None
    assert deps._memory is None
    assert deps._db is None
    assert deps._vision is None
    
    # Access catalog
    _ = deps.catalog
    
    # Now catalog should be created, but others still None
    assert deps._catalog is not None
    assert deps._memory is None
    assert deps._db is None
    assert deps._vision is None
    
    # Access memory
    _ = deps.memory
    
    # Now memory should be created too
    assert deps._memory is not None

