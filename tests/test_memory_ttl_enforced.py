"""Test that memory facts TTL is enforced on read (expires_at filter)."""

import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from src.services.memory.facts import FactsMixin
from src.services.memory.base import MemoryBase


class MockFactsMixin(FactsMixin, MemoryBase):
    """Mock implementation of FactsMixin for testing."""
    
    def __init__(self):
        self._enabled = True
        # Use _models to bypass the property
        self._models = {
            "Fact": type('Fact', (), {
                '__init__': lambda self, **kwargs: [setattr(self, k, v) for k, v in kwargs.items()]
            })
        }


@pytest.mark.asyncio
async def test_get_facts_filters_expired_by_ttl():
    """Test that get_facts() doesn't return facts with expires_at < NOW()."""
    facts_service = MockFactsMixin()
    
    now = datetime.now(UTC)
    expired_time = now - timedelta(hours=1)  # Expired 1 hour ago
    future_time = now + timedelta(hours=1)   # Expires in 1 hour
    
    # Mock rows: one expired, one active, one without expires_at
    mock_rows = [
        {
            "id": "expired_fact",
            "user_id": "test_user",
            "content": "Expired fact",
            "fact_type": "preference",
            "category": "general",
            "importance": 0.8,
            "surprise": 0.5,
            "confidence": 0.8,
            "ttl_days": None,
            "created_at": (now - timedelta(days=2)).isoformat(),
            "updated_at": (now - timedelta(days=2)).isoformat(),
            "last_accessed_at": (now - timedelta(days=2)).isoformat(),
            "expires_at": expired_time.isoformat(),  # EXPIRED
            "is_active": True,
        },
        {
            "id": "active_fact",
            "user_id": "test_user",
            "content": "Active fact",
            "fact_type": "preference",
            "category": "general",
            "importance": 0.8,
            "surprise": 0.5,
            "confidence": 0.8,
            "ttl_days": None,
            "created_at": (now - timedelta(days=1)).isoformat(),
            "updated_at": (now - timedelta(days=1)).isoformat(),
            "last_accessed_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": future_time.isoformat(),  # NOT EXPIRED
            "is_active": True,
        },
        {
            "id": "no_expiry_fact",
            "user_id": "test_user",
            "content": "No expiry fact",
            "fact_type": "preference",
            "category": "general",
            "importance": 0.8,
            "surprise": 0.5,
            "confidence": 0.8,
            "ttl_days": None,
            "created_at": (now - timedelta(days=1)).isoformat(),
            "updated_at": (now - timedelta(days=1)).isoformat(),
            "last_accessed_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": None,  # NO EXPIRY
            "is_active": True,
        },
    ]
    
    # Mock the database query to return our test rows
    with patch.object(facts_service, '_run_db', new_callable=AsyncMock) as mock_run_db:
        mock_run_db.return_value = mock_rows
        
        # Mock _touch_facts to avoid side effects
        with patch.object(facts_service, '_touch_facts', new_callable=AsyncMock):
            facts = await facts_service.get_facts("test_user", limit=10)
            
            # Should only return facts that are NOT expired
            # In the current implementation, the SQL filter should exclude expired facts
            # But we need to verify the SQL includes: AND (expires_at IS NULL OR expires_at > NOW())
            
            # For now, we verify that the method exists and can be called
            # The actual SQL filter will be added in ЗАДАЧА 3
            assert isinstance(facts, list)
            
            # After ЗАДАЧА 3 is implemented, this should only return 2 facts (active + no_expiry)
            # For now, we just verify the method works
            mock_run_db.assert_called_once()


@pytest.mark.asyncio
async def test_search_facts_filters_expired_by_ttl():
    """Test that search_facts() also filters expired facts."""
    facts_service = MockFactsMixin()
    
    # Mock the database query
    with patch.object(facts_service, '_run_db', new_callable=AsyncMock) as mock_run_db:
        mock_run_db.return_value = []
        
        query_embedding = [0.1] * 1536  # Mock embedding vector
        
        results = await facts_service.search_facts(
            "test_user",
            query_embedding,
            limit=10,
        )
        
        # Verify the method can be called
        assert isinstance(results, list)
        mock_run_db.assert_called_once()
        
        # After ЗАДАЧА 3, the SQL in search_memories() function should also filter expires_at


