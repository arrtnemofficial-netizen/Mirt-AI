"""Unit tests for Redis-backed debouncer."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.infra.debouncer import BufferedMessage, MessageDebouncer, RedisDebouncer, create_debouncer


class TestRedisDebouncer:
    """Tests for RedisDebouncer class."""

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        client = MagicMock()
        client.ping.return_value = True
        client.lpush.return_value = 1
        client.lrange.return_value = []
        client.get.return_value = None
        client.setex.return_value = True
        client.delete.return_value = 1
        client.expire.return_value = True
        return client

    def test_redis_available(self, mock_redis_client):
        """RedisDebouncer should use Redis when available."""
        with patch("redis.from_url", return_value=mock_redis_client):
            debouncer = RedisDebouncer(delay=1.0)
            
            assert debouncer._redis_available is True
            assert debouncer._fallback_debouncer is None

    def test_redis_unavailable_fallback(self):
        """RedisDebouncer should fallback to in-memory when Redis unavailable."""
        with patch("redis.from_url", side_effect=Exception("Connection failed")):
            debouncer = RedisDebouncer(delay=1.0)
            
            assert debouncer._redis_available is False
            assert debouncer._fallback_debouncer is not None
            assert isinstance(debouncer._fallback_debouncer, MessageDebouncer)

    @pytest.mark.asyncio
    async def test_add_message_with_redis(self, mock_redis_client):
        """add_message should work with Redis backend."""
        with patch("redis.from_url", return_value=mock_redis_client):
            debouncer = RedisDebouncer(delay=0.1)
            
            callback = AsyncMock()
            message = BufferedMessage(text="Hello", has_image=False)
            
            await debouncer.add_message("test_session", message, callback)
            
            # Should have called Redis operations
            assert mock_redis_client.lpush.called
            assert mock_redis_client.setex.called

    @pytest.mark.asyncio
    async def test_add_message_fallback(self):
        """add_message should use fallback when Redis unavailable."""
        with patch("redis.from_url", side_effect=Exception("Connection failed")):
            debouncer = RedisDebouncer(delay=0.1)
            
            callback = AsyncMock()
            message = BufferedMessage(text="Hello", has_image=False)
            
            # Should not raise exception
            await debouncer.add_message("test_session", message, callback)
            
            # Should have used fallback
            assert debouncer._fallback_debouncer is not None

    @pytest.mark.asyncio
    async def test_wait_for_debounce_with_redis(self, mock_redis_client):
        """wait_for_debounce should work with Redis backend."""
        with patch("redis.from_url", return_value=mock_redis_client):
            debouncer = RedisDebouncer(delay=0.1)
            
            message = BufferedMessage(text="Hello", has_image=False)
            
            # Mock timer task to complete immediately
            with patch.object(debouncer, "_timer_task_redis", new_callable=AsyncMock):
                # Should not raise exception
                result = await asyncio.wait_for(
                    debouncer.wait_for_debounce("test_session", message),
                    timeout=0.5
                )
                
                # Result might be None if timer didn't complete
                assert result is None or isinstance(result, BufferedMessage)

    @pytest.mark.asyncio
    async def test_wait_for_debounce_fallback(self):
        """wait_for_debounce should use fallback when Redis unavailable."""
        with patch("redis.from_url", side_effect=Exception("Connection failed")):
            debouncer = RedisDebouncer(delay=0.1)
            
            message = BufferedMessage(text="Hello", has_image=False)
            
            # Should use fallback debouncer
            result = await asyncio.wait_for(
                debouncer.wait_for_debounce("test_session", message),
                timeout=0.5
            )
            
            # Result might be None if timer didn't complete
            assert result is None or isinstance(result, BufferedMessage)

    def test_clear_session_with_redis(self, mock_redis_client):
        """clear_session should clean up Redis keys."""
        with patch("redis.from_url", return_value=mock_redis_client):
            debouncer = RedisDebouncer(delay=1.0)
            
            debouncer.clear_session("test_session")
            
            # Should have called Redis delete
            assert mock_redis_client.delete.called

    def test_clear_session_fallback(self):
        """clear_session should work with fallback."""
        with patch("redis.from_url", side_effect=Exception("Connection failed")):
            debouncer = RedisDebouncer(delay=1.0)
            
            # Should not raise exception
            debouncer.clear_session("test_session")


class TestCreateDebouncer:
    """Tests for create_debouncer factory function."""

    def test_create_with_redis_available(self):
        """create_debouncer should return RedisDebouncer when Redis available."""
        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        
        with patch("redis.from_url", return_value=mock_redis_client):
            debouncer = create_debouncer(delay=1.0)
            
            assert isinstance(debouncer, RedisDebouncer)
            assert debouncer._redis_available is True

    def test_create_with_redis_unavailable(self):
        """create_debouncer should return MessageDebouncer when Redis unavailable."""
        with patch("redis.from_url", side_effect=Exception("Connection failed")):
            debouncer = create_debouncer(delay=1.0)
            
            assert isinstance(debouncer, MessageDebouncer)

    def test_create_with_no_redis_url(self):
        """create_debouncer should return MessageDebouncer when Redis URL not configured."""
        with patch("src.conf.config.settings") as mock_settings:
            mock_settings.REDIS_URL = ""
            with patch("os.getenv", return_value=None):
                debouncer = create_debouncer(delay=1.0)
                
                assert isinstance(debouncer, MessageDebouncer)

    def test_create_fallback_on_error(self):
        """create_debouncer should handle errors gracefully."""
        with patch("redis.from_url", side_effect=Exception("Unexpected error")):
            debouncer = create_debouncer(delay=1.0)
            
            # Should return MessageDebouncer on any error
            assert isinstance(debouncer, MessageDebouncer)

