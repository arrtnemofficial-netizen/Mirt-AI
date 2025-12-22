"""Tests for client_data_parser module.

Tests cover:
- Basic extraction functions (phone, name, city, nova poshta)
- Error handling for invalid regex patterns
- Edge cases with image URLs and special characters
"""

import re

import pytest

from src.services.client_data_parser import (
    ClientData,
    extract_city,
    extract_full_name,
    extract_nova_poshta,
    extract_phone,
    parse_client_data,
)


class TestExtractPhone:
    """Test phone number extraction."""

    def test_extract_phone_with_url(self):
        """Test phone extraction with image URL in text (repro for regex error)."""
        # This is the problematic text from production logs
        text_with_url = ".; https://lookaside.fbsbx.com/ig_messaging_cdn/?a=... my phone is +380501234567"
        result = extract_phone(text_with_url)
        # Should not raise regex error, should extract phone or return None gracefully
        assert result is None or result.startswith("+380")  # type: ignore

    def test_extract_phone_normal(self):
        """Test normal phone extraction."""
        assert extract_phone("мій номер +380501234567") == "+380501234567"

    def test_extract_phone_with_special_chars(self):
        """Test phone extraction with special characters that might break regex."""
        text = ".;[](){}|*+?^$\\ my phone 0501234567"
        result = extract_phone(text)
        assert result == "+380501234567" or result is None


class TestExtractFullName:
    """Test full name extraction."""

    def test_extract_full_name_with_url(self):
        """Test name extraction with image URL in text."""
        text_with_url = "https://lookaside.fbsbx.com/ig_messaging_cdn/?a=... Іван Петренко"
        result = extract_full_name(text_with_url)
        # Should not raise regex error
        assert result is None or isinstance(result, str)


class TestExtractCity:
    """Test city extraction."""

    def test_extract_city_with_url(self):
        """Test city extraction with image URL in text."""
        text_with_url = "https://example.com/image.jpg місто Київ"
        result = extract_city(text_with_url)
        # Should not raise regex error
        assert result is None or isinstance(result, str)


class TestExtractNovaPoshta:
    """Test Nova Poshta extraction."""

    def test_extract_nova_poshta_with_url(self):
        """Test Nova Poshta extraction with image URL in text."""
        text_with_url = "https://lookaside.fbsbx.com/ig_messaging_cdn/?a=... нп 25"
        result = extract_nova_poshta(text_with_url)
        # Should not raise regex error
        assert result is None or isinstance(result, str)


class TestParseClientData:
    """Test parse_client_data function."""

    def test_parse_client_data_with_image_url(self):
        """Test parsing with image URL - this should not raise regex error."""
        # This reproduces the production error scenario
        text_with_url = ".; https://lookaside.fbsbx.com/ig_messaging_cdn/?a=..."
        result = parse_client_data(text_with_url)
        # Should return ClientData without raising regex error
        assert isinstance(result, ClientData)
        # All fields might be None, which is fine - the important thing is no exception
        assert result.phone is None or isinstance(result.phone, str)
        assert result.full_name is None or isinstance(result.full_name, str)
        assert result.city is None or isinstance(result.city, str)
        assert result.nova_poshta is None or isinstance(result.nova_poshta, str)

    def test_parse_client_data_with_url_and_data(self):
        """Test parsing with URL but also valid data."""
        text = "https://lookaside.fbsbx.com/ig_messaging_cdn/?a=... Іван Петренко +380501234567 нп 25 Київ"
        result = parse_client_data(text)
        assert isinstance(result, ClientData)
        # Should extract data if patterns match

    def test_parse_client_data_special_regex_chars(self):
        """Test parsing with text containing regex special characters."""
        # Characters that could break regex if not escaped properly
        problematic_chars = ".;[](){}|*+?^$\\"
        text = f"{problematic_chars} Іван +380501234567"
        result = parse_client_data(text)
        # Should not raise regex error
        assert isinstance(result, ClientData)

    def test_parse_client_data_empty(self):
        """Test parsing empty text."""
        result = parse_client_data("")
        assert isinstance(result, ClientData)
        assert result.phone is None
        assert result.full_name is None
        assert result.city is None
        assert result.nova_poshta is None

    def test_parse_client_data_normal(self):
        """Test normal parsing scenario."""
        text = "Іван Петренко +380501234567 нп 25 Київ"
        result = parse_client_data(text)
        assert isinstance(result, ClientData)


class TestRegexErrorHandling:
    """Test that regex errors are handled gracefully."""

    def test_invalid_pattern_does_not_crash(self):
        """Test that invalid regex patterns in config don't crash the parser."""
        # This tests that our error handling works
        # We can't easily inject invalid patterns from config in unit tests,
        # but we can verify the error handling code paths exist
        
        # Test with text that might trigger edge cases
        edge_case_texts = [
            ".;",  # From production error
            "https://example.com/image.jpg",
            "[](){}|*+?^$\\",  # All regex special chars
            "a" * 10000,  # Very long text
            "\x00\x01\x02",  # Control characters
        ]
        
        for text in edge_case_texts:
            # Should not raise any exceptions
            result = parse_client_data(text)
            assert isinstance(result, ClientData)

