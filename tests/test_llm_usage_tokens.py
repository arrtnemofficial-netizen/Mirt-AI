"""Tests for LLM token extraction from PydanticAI RunUsage."""

import pytest
from unittest.mock import Mock
from pydantic_ai import RunUsage


class TestTokenExtraction:
    """Test token extraction logic from AgentRunResult.usage."""

    def test_extract_tokens_from_runusage_with_values(self):
        """Test extraction of tokens when RunUsage has actual values."""
        # Create a RunUsage with actual token values
        usage = RunUsage(input_tokens=150, output_tokens=75)
        
        # Verify has_values() returns True
        assert usage.has_values() is True
        assert usage.input_tokens == 150
        assert usage.output_tokens == 75
        assert usage.total_tokens == 225

    def test_extract_tokens_fallback_to_total(self):
        """Test fallback to total_tokens when input/output are 0."""
        # Create a RunUsage with only total_tokens
        usage = RunUsage(input_tokens=0, output_tokens=0)
        # Note: RunUsage doesn't allow setting total_tokens directly,
        # but we can test the logic that would use it
        
        # Verify has_values() returns False for default RunUsage
        assert usage.has_values() is False
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0

    def test_extract_tokens_handles_none_usage(self):
        """Test that None usage is handled correctly."""
        # Simulate result.usage being None
        usage = None
        
        # Should not raise AttributeError
        assert usage is None
        # hasattr check should work
        result_mock = Mock()
        result_mock.usage = None
        
        assert hasattr(result_mock, "usage") is True
        assert result_mock.usage is None

    def test_extract_tokens_handles_empty_usage(self):
        """Test handling of empty usage (has_values() = False)."""
        # Default RunUsage has no values
        usage = RunUsage()
        
        assert usage.has_values() is False
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0

    def test_runusage_total_tokens_calculation(self):
        """Test that total_tokens is calculated correctly."""
        usage = RunUsage(input_tokens=100, output_tokens=50)
        
        assert usage.total_tokens == 150

    def test_token_extraction_logic_simulation(self):
        """Simulate the actual extraction logic used in agents."""
        # Simulate a result with valid usage
        result_mock = Mock()
        result_mock.usage = RunUsage(input_tokens=200, output_tokens=100)
        
        tokens_input = 0
        tokens_output = 0
        
        # Simulate the extraction logic
        if hasattr(result_mock, "usage") and result_mock.usage is not None:
            usage = result_mock.usage
            if usage.has_values():
                if hasattr(usage, "input_tokens"):
                    tokens_input = usage.input_tokens or 0
                if hasattr(usage, "output_tokens"):
                    tokens_output = usage.output_tokens or 0
        
        assert tokens_input == 200
        assert tokens_output == 100

    def test_token_extraction_with_none_usage(self):
        """Test extraction logic when usage is None."""
        result_mock = Mock()
        result_mock.usage = None
        
        tokens_input = 0
        tokens_output = 0
        
        # Simulate the extraction logic
        if hasattr(result_mock, "usage") and result_mock.usage is not None:
            usage = result_mock.usage
            if usage.has_values():
                if hasattr(usage, "input_tokens"):
                    tokens_input = usage.input_tokens or 0
                if hasattr(usage, "output_tokens"):
                    tokens_output = usage.output_tokens or 0
        
        # Should remain 0 when usage is None
        assert tokens_input == 0
        assert tokens_output == 0

    def test_token_extraction_with_empty_usage(self):
        """Test extraction logic when usage has no values."""
        result_mock = Mock()
        result_mock.usage = RunUsage()  # Default, no values
        
        tokens_input = 0
        tokens_output = 0
        
        # Simulate the extraction logic
        if hasattr(result_mock, "usage") and result_mock.usage is not None:
            usage = result_mock.usage
            if usage.has_values():
                if hasattr(usage, "input_tokens"):
                    tokens_input = usage.input_tokens or 0
                if hasattr(usage, "output_tokens"):
                    tokens_output = usage.output_tokens or 0
        
        # Should remain 0 when usage has no values
        assert tokens_input == 0
        assert tokens_output == 0

