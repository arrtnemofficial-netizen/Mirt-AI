"""Unit tests for checkpointer payload size limit."""

from unittest.mock import MagicMock, patch

import pytest

from src.agents.langgraph.checkpointer import InstrumentedAsyncPostgresSaver


class TestPayloadSizeLimit:
    """Tests for payload size limit checking."""

    def test_payload_within_limit(self):
        """Payload within limit should not log warning."""
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
        
        # Small payload
        small_payload = {
            "channel_values": {
                "messages": [{"role": "user", "content": "Hello"}],
                "metadata": {"session_id": "test_123"},
            }
        }
        
        with patch("src.conf.config.get_settings") as mock_settings:
            mock_settings.return_value.CHECKPOINTER_MAX_PAYLOAD_SIZE_BYTES = 512 * 1024
            
            result = saver._process_payload(small_payload)
            
            # Should return compacted payload without warnings
            assert result is not None
            assert isinstance(result, dict)

    def test_payload_exceeds_limit(self):
        """Payload exceeding limit should log warning but not block."""
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
        
        # Create large payload (many long messages)
        large_payload = {
            "channel_values": {
                "messages": [
                    {"role": "user", "content": "A" * 10000} for _ in range(100)
                ],
                "metadata": {"session_id": "test_large_123"},
            }
        }
        
        with patch("src.conf.config.get_settings") as mock_settings, \
             patch("src.agents.langgraph.checkpointer.logger") as mock_logger, \
             patch("src.services.core.observability.track_metric") as mock_metric:
            
            # Set very low limit for testing
            mock_settings.return_value.CHECKPOINTER_MAX_PAYLOAD_SIZE_BYTES = 1000
            
            result = saver._process_payload(large_payload)
            
            # Should still return payload (not blocked)
            assert result is not None
            assert isinstance(result, dict)
            
            # Should log warning
            mock_logger.warning.assert_called()
            warning_call = str(mock_logger.warning.call_args)
            assert "exceeds limit" in warning_call or "Payload size" in warning_call
            
            # Should track metric
            mock_metric.assert_called()
            metric_call = mock_metric.call_args
            assert metric_call[0][0] == "checkpointer_payload_too_large"

    def test_payload_limit_with_session_id(self):
        """Payload limit check should extract session_id correctly."""
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
        
        large_payload = {
            "channel_values": {
                "messages": [{"role": "user", "content": "A" * 5000}],
                "metadata": {"session_id": "test_session_456"},
            }
        }
        
        with patch("src.conf.config.get_settings") as mock_settings, \
             patch("src.agents.langgraph.checkpointer.logger") as mock_logger:
            
            mock_settings.return_value.CHECKPOINTER_MAX_PAYLOAD_SIZE_BYTES = 1000
            
            result = saver._process_payload(large_payload)
            
            # Check that session_id was extracted
            warning_call = str(mock_logger.warning.call_args)
            assert "test_session_456" in warning_call or "unknown" in warning_call

    def test_payload_limit_fallback_on_error(self):
        """If limit check fails, should continue without blocking."""
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
        
        payload = {
            "channel_values": {
                "messages": [{"role": "user", "content": "Hello"}],
                "metadata": {"session_id": "test_123"},
            }
        }
        
        # Simulate error only in the limit check part (after compaction)
        # We need to patch get_settings to work for compaction but fail for limit check
        call_count = [0]
        original_get_settings = None
        
        def mock_get_settings():
            call_count[0] += 1
            # First call is for compaction (should succeed)
            if call_count[0] == 1:
                from src.conf.config import Settings
                return Settings()
            # Second call is for limit check (should fail)
            raise Exception("Settings error")
        
        with patch("src.conf.config.get_settings", side_effect=mock_get_settings), \
             patch("src.agents.langgraph.checkpointer.logger") as mock_logger:
            
            # Should not raise exception even if limit check fails
            result = saver._process_payload(payload)
            
            assert result is not None
            # Should log debug message about failure in limit check
            debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
            assert any("Failed to check payload size limit" in str(call) for call in debug_calls)

    def test_none_payload(self):
        """None payload should return None without checking limit."""
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
        
        result = saver._process_payload(None)
        
        assert result is None

