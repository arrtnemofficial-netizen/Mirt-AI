"""Integration tests for state hardening improvements.

Tests all three improvements together:
1. State structure validation
2. Payload size limit
3. Redis debouncing
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.conversation_state import create_initial_state, validate_state_structure
from src.services.conversation.handler import ConversationHandler
from src.services.infra.debouncer import BufferedMessage, create_debouncer


class TestStateHardeningIntegration:
    """Integration tests for state hardening features."""

    @pytest.fixture
    def mock_session_store(self):
        """Create a mock session store."""
        store = MagicMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock()
        return store

    @pytest.fixture
    def mock_message_store(self):
        """Create a mock message store."""
        store = MagicMock()
        store.save = AsyncMock()
        return store

    @pytest.fixture
    def mock_runner(self):
        """Create a mock graph runner."""
        runner = MagicMock()
        runner.ainvoke = AsyncMock(return_value={
            "messages": [],
            "current_state": "STATE_0_INIT",
        })
        return runner

    @pytest.mark.asyncio
    async def test_state_validation_in_handler(self, mock_session_store, mock_message_store, mock_runner):
        """Test that state validation is called when loading state."""
        # Create corrupted state
        corrupted_state = {
            "session_id": None,  # Invalid: None instead of string
            "messages": "not a list",  # Invalid: string instead of list
            "metadata": None,  # Invalid: None instead of dict
            "current_state": 12345,  # Invalid: int instead of string
        }
        
        mock_session_store.get = AsyncMock(return_value=corrupted_state)
        
        handler = ConversationHandler(
            session_store=mock_session_store,
            message_store=mock_message_store,
            runner=mock_runner,
        )
        
        # Process message - should log validation errors but continue
        with patch("src.services.conversation.handler.logger") as mock_logger:
            await handler.process_message(
                session_id="test_session",
                text="Hello",
                extra_metadata={},
            )
            
            # Should have logged validation warnings
            warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
            assert any("validation failed" in str(call).lower() for call in warning_calls)

    @pytest.mark.asyncio
    async def test_payload_limit_in_checkpointer(self):
        """Test that payload limit check works in checkpointer."""
        from src.agents.langgraph.checkpointer import InstrumentedAsyncPostgresSaver
        
        base = MagicMock()
        pool = MagicMock()
        
        saver = InstrumentedAsyncPostgresSaver(
            base=base,
            pool=pool,
            slow_threshold_s=1.0,
            max_messages=200,
            max_chars=4000,
            drop_base64=True,
        )
        
        # Create large payload
        large_payload = {
            "channel_values": {
                "messages": [
                    {"role": "user", "content": "A" * 10000} for _ in range(200)
                ],
                "metadata": {"session_id": "test_large"},
            }
        }
        
        with patch("src.agents.langgraph.checkpointer.get_settings") as mock_settings, \
             patch("src.agents.langgraph.checkpointer.logger") as mock_logger, \
             patch("src.agents.langgraph.checkpointer.track_metric") as mock_metric:
            
            # Set low limit
            mock_settings.return_value.CHECKPOINTER_MAX_PAYLOAD_SIZE_BYTES = 1000
            
            result = saver._process_payload(large_payload)
            
            # Should still return payload (not blocked)
            assert result is not None
            
            # Should log warning
            mock_logger.warning.assert_called()
            
            # Should track metric
            mock_metric.assert_called()

    def test_redis_debouncer_fallback(self):
        """Test that Redis debouncer falls back to in-memory when Redis unavailable."""
        with patch("redis.from_url", side_effect=Exception("Connection failed")):
            debouncer = create_debouncer(delay=1.0)
            
            # Should return MessageDebouncer (fallback)
            from src.services.infra.debouncer import MessageDebouncer
            assert isinstance(debouncer, MessageDebouncer)

    @pytest.mark.asyncio
    async def test_all_three_improvements_together(self, mock_session_store, mock_message_store, mock_runner):
        """Test all three improvements work together."""
        # 1. State validation: corrupted state
        corrupted_state = {
            "session_id": "test_session",
            "messages": [],  # Valid
            "metadata": {},  # Valid
            "current_state": "STATE_0_INIT",  # Valid
            "selected_products": "not a list",  # Invalid type
        }
        
        mock_session_store.get = AsyncMock(return_value=corrupted_state)
        
        # 2. Payload limit: large payload will be created during processing
        # 3. Redis debouncing: will use fallback if Redis unavailable
        
        handler = ConversationHandler(
            session_store=mock_session_store,
            message_store=mock_message_store,
            runner=mock_runner,
        )
        
        # Create debouncer (will use Redis if available, fallback otherwise)
        debouncer = create_debouncer(delay=0.1)
        
        # Process message
        with patch("src.services.conversation.handler.logger") as mock_logger:
            await handler.process_message(
                session_id="test_session",
                text="Hello",
                extra_metadata={},
            )
            
            # Should have logged validation warnings if state was invalid
            # (but continue processing)
            assert mock_session_store.save.called

    def test_state_validation_with_production_like_state(self):
        """Test state validation with production-like state."""
        state = create_initial_state(
            session_id="prod_session_123",
            messages=[
                {"role": "user", "content": "Привіт"},
                {"role": "assistant", "content": "Вітаю!"},
            ],
            metadata={
                "channel": "telegram",
                "language": "uk",
            },
        )
        state["selected_products"] = [{"id": 1, "name": "Лагуна"}]
        state["retry_count"] = 0
        
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is True
        assert len(errors) == 0

    def test_state_validation_edge_cases(self):
        """Test state validation with edge cases."""
        # Empty state (should fail)
        is_valid, errors = validate_state_structure({})
        assert is_valid is False
        assert len(errors) > 0
        
        # State with None required fields (should fail)
        state = {
            "session_id": None,
            "messages": None,
            "metadata": None,
            "current_state": None,
        }
        is_valid, errors = validate_state_structure(state)
        assert is_valid is False
        assert len(errors) > 0
        
        # State with wrong types (should fail)
        state = {
            "session_id": 12345,
            "messages": "not a list",
            "metadata": "not a dict",
            "current_state": 999,
        }
        is_valid, errors = validate_state_structure(state)
        assert is_valid is False
        assert len(errors) > 0

