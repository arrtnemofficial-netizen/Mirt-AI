"""
Unit tests for LLM usage logger.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.llm_usage_logger import (
    _sanitize_metadata,
    log_llm_usage_best_effort,
)


class TestSanitizeMetadata:
    """Tests for _sanitize_metadata function."""

    def test_sanitize_keeps_safe_fields(self):
        """Test that safe fields are kept."""
        metadata = {
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
            "current_state": "STATE_5_PAYMENT_DELIVERY",
            "intent": "PAYMENT_DELIVERY",
            "policy_case": "user_says_no",
            "has_image": True,
            "confidence": 0.95,
            "detected_product_id": "prod_123",
            "detected_product_name": "Костюм Каприз",
        }
        
        result = _sanitize_metadata(metadata)
        
        assert result == metadata

    def test_sanitize_removes_unsafe_fields(self):
        """Test that unsafe fields are removed."""
        metadata = {
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
            "unsafe_field": "should be removed",
            "large_snapshot": "x" * 10000,  # Large field
        }
        
        result = _sanitize_metadata(metadata)
        
        assert "dialog_phase" in result
        assert "unsafe_field" not in result
        assert "large_snapshot" not in result

    def test_sanitize_image_url_extracts_host(self):
        """Test that image_url is converted to host only."""
        metadata = {
            "image_url": "https://example.com/path/to/image.jpg?token=secret",
            "dialog_phase": "DISCOVERY",
        }
        
        result = _sanitize_metadata(metadata)
        
        assert "image_url" not in result
        assert result["image_url_host"] == "example.com"
        assert result["dialog_phase"] == "DISCOVERY"

    def test_sanitize_image_url_host_preserved(self):
        """Test that image_url_host is preserved."""
        metadata = {
            "image_url_host": "example.com",
            "dialog_phase": "DISCOVERY",
        }
        
        result = _sanitize_metadata(metadata)
        
        assert result["image_url_host"] == "example.com"


class TestLogLlmUsageBestEffort:
    """Tests for log_llm_usage_best_effort function."""

    @pytest.mark.asyncio
    async def test_logs_successful_usage(self):
        """Test logging successful LLM usage."""
        with patch("src.services.llm_usage_logger.get_postgres_url", return_value="postgresql://test"):
            with patch("src.services.llm_usage_logger.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = AsyncMock()
                with patch("src.services.llm_usage_logger.asyncio.wait_for") as mock_wait:
                    mock_wait.return_value = AsyncMock()
                    
                    await log_llm_usage_best_effort(
                        session_id="test_session",
                        model="gpt-4o-mini",
                        tokens_input=100,
                        tokens_output=50,
                        latency_ms=150.5,
                        success=True,
                    )
                    
                    # Should call asyncio.wait_for
                    assert mock_wait.called

    @pytest.mark.asyncio
    async def test_skips_if_no_model(self):
        """Test that logging is skipped if model is None."""
        with patch("src.services.llm_usage_logger.get_postgres_url"):
            with patch("src.services.llm_usage_logger.asyncio.to_thread") as mock_to_thread:
                await log_llm_usage_best_effort(
                    session_id="test_session",
                    model=None,
                    tokens_input=100,
                    tokens_output=50,
                    latency_ms=150.5,
                )
                
                # Should not call asyncio.to_thread
                assert not mock_to_thread.called

    @pytest.mark.asyncio
    async def test_skips_if_negative_tokens(self):
        """Test that logging is skipped if tokens are negative."""
        with patch("src.services.llm_usage_logger.get_postgres_url"):
            with patch("src.services.llm_usage_logger.asyncio.to_thread") as mock_to_thread:
                await log_llm_usage_best_effort(
                    session_id="test_session",
                    model="gpt-4o-mini",
                    tokens_input=-1,
                    tokens_output=50,
                    latency_ms=150.5,
                )
                
                # Should not call asyncio.to_thread
                assert not mock_to_thread.called

    @pytest.mark.asyncio
    async def test_handles_timeout_gracefully(self):
        """Test that timeout is handled gracefully."""
        import asyncio
        
        with patch("src.services.llm_usage_logger.get_postgres_url", return_value="postgresql://test"):
            with patch("src.services.llm_usage_logger.asyncio.wait_for") as mock_wait:
                mock_wait.side_effect = asyncio.TimeoutError()
                
                # Should not raise exception
                await log_llm_usage_best_effort(
                    session_id="test_session",
                    model="gpt-4o-mini",
                    tokens_input=100,
                    tokens_output=50,
                    latency_ms=150.5,
                )

    @pytest.mark.asyncio
    async def test_handles_db_error_gracefully(self):
        """Test that DB errors are handled gracefully."""
        with patch("src.services.llm_usage_logger.get_postgres_url", return_value="postgresql://test"):
            with patch("src.services.llm_usage_logger.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = AsyncMock()
                with patch("src.services.llm_usage_logger.asyncio.wait_for") as mock_wait:
                    mock_wait.side_effect = Exception("DB connection failed")
                    
                    # Should not raise exception
                    await log_llm_usage_best_effort(
                        session_id="test_session",
                        model="gpt-4o-mini",
                        tokens_input=100,
                        tokens_output=50,
                        latency_ms=150.5,
                    )

    @pytest.mark.asyncio
    async def test_logs_with_metadata(self):
        """Test logging with metadata."""
        with patch("src.services.llm_usage_logger.get_postgres_url", return_value="postgresql://test"):
            with patch("src.services.llm_usage_logger.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = AsyncMock()
                with patch("src.services.llm_usage_logger.asyncio.wait_for") as mock_wait:
                    mock_wait.return_value = AsyncMock()
                    
                    metadata = {
                        "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
                        "current_state": "STATE_5_PAYMENT_DELIVERY",
                        "has_image": True,
                    }
                    
                    await log_llm_usage_best_effort(
                        session_id="test_session",
                        model="gpt-4o-mini",
                        tokens_input=100,
                        tokens_output=50,
                        latency_ms=150.5,
                        metadata=metadata,
                    )
                    
                    # Should call asyncio.wait_for
                    assert mock_wait.called

    @pytest.mark.asyncio
    async def test_logs_error_case(self):
        """Test logging error case."""
        with patch("src.services.llm_usage_logger.get_postgres_url", return_value="postgresql://test"):
            with patch("src.services.llm_usage_logger.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = AsyncMock()
                with patch("src.services.llm_usage_logger.asyncio.wait_for") as mock_wait:
                    mock_wait.return_value = AsyncMock()
                    
                    await log_llm_usage_best_effort(
                        session_id="test_session",
                        model="gpt-4o-mini",
                        tokens_input=0,
                        tokens_output=0,
                        latency_ms=150.5,
                        success=False,
                        error_message="LLM_TIMEOUT",
                    )
                    
                    # Should call asyncio.wait_for
                    assert mock_wait.called

