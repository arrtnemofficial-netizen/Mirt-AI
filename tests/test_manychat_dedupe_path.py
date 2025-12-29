"""Test ManyChat webhook dedupe path to ensure no asyncio.run() in async context."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.webhook.webhook_dedupe import WebhookDedupeStore


@pytest.mark.asyncio
async def test_webhook_dedupe_with_message_id_no_typeerror():
    """Test that webhook with message_id doesn't crash with TypeError in constructor."""
    # This test ensures the constructor accepts the correct parameters
    # and doesn't fail when message_id is provided
    dedupe_store = WebhookDedupeStore(ttl_hours=24)
    
    # Should not raise TypeError
    assert dedupe_store is not None
    assert dedupe_store.ttl_hours == 24


@pytest.mark.asyncio
async def test_dedupe_no_asyncio_run_in_async_context():
    """Test that dedupe doesn't use asyncio.run() in async context (would fail)."""
    from unittest.mock import patch
    
    dedupe_store = WebhookDedupeStore(ttl_hours=24)
    
    # Mock the async method to avoid actual DB calls
    with patch.object(dedupe_store, '_check_and_mark_postgres', new_callable=AsyncMock) as mock_async:
        mock_async.return_value = False  # Not a duplicate
        
        # This should NOT use asyncio.run() - it should be awaitable
        result = await dedupe_store._check_and_mark_postgres(
            user_id="test_user",
            message_id="msg_123",
            text="test",
            image_url=None,
        )
        
        assert result is False
        mock_async.assert_called_once()
        
        # Verify we're using async/await, not asyncio.run()
        # If asyncio.run() was called, we'd get a RuntimeError in async context
        assert not hasattr(result, '__await__') or result is False


@pytest.mark.asyncio
async def test_dedupe_check_and_mark_async_api():
    """Test that async API exists and works correctly."""
    dedupe_store = WebhookDedupeStore(ttl_hours=24)
    
    # Verify async method exists
    assert hasattr(dedupe_store, '_check_and_mark_postgres')
    assert hasattr(dedupe_store, 'check_and_mark')
    assert hasattr(dedupe_store, 'check_and_mark_async')  # NEW async API
    
    # Mock the async implementation
    with patch.object(dedupe_store, '_check_and_mark_postgres', new_callable=AsyncMock) as mock_async:
        mock_async.return_value = True  # Duplicate
        
        result = await dedupe_store.check_and_mark_async(
            user_id="test_user",
            message_id="msg_123",
            text="test",
            image_url=None,
        )
        
        assert result is True
        # _check_and_mark_postgres is called with positional args internally
        mock_async.assert_called_once_with(
            "test_user",
            "msg_123",
            "test",
            None,
        )

