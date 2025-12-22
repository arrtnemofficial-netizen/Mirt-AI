"""Unit tests for security utilities."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.core.security import (
    require_token_validation,
    secure_token_compare,
    validate_image_url,
)


class TestSecureTokenCompare:
    """Tests for secure_token_compare function."""

    def test_matching_tokens(self):
        """Test that matching tokens return True."""
        token = "secret_token_123"
        assert secure_token_compare(token, token) is True

    def test_different_tokens(self):
        """Test that different tokens return False."""
        assert secure_token_compare("token1", "token2") is False

    def test_empty_tokens(self):
        """Test that empty tokens return False."""
        assert secure_token_compare("", "") is False
        assert secure_token_compare("token", "") is False
        assert secure_token_compare("", "token") is False

    def test_none_tokens(self):
        """Test that None tokens are handled."""
        assert secure_token_compare("token", None) is False
        assert secure_token_compare(None, "token") is False
        assert secure_token_compare(None, None) is False

    def test_timing_safe_comparison(self):
        """Test that comparison uses secrets.compare_digest (timing-safe)."""
        assert secure_token_compare("short", "longer_token") is False
        assert secure_token_compare("same_length_123", "same_length_456") is False


class TestValidateImageUrl:
    """Tests for validate_image_url function."""

    def test_valid_https_url(self):
        """Test that valid HTTPS URLs pass validation."""
        url = "https://example.com/image.jpg"
        is_valid, error = validate_image_url(url)
        assert is_valid is True
        assert error is None

    def test_valid_http_url(self):
        """Test that valid HTTP URLs pass validation."""
        url = "http://example.com/image.jpg"
        is_valid, error = validate_image_url(url)
        assert is_valid is True
        assert error is None

    def test_localhost_blocked(self):
        """Test that localhost URLs are blocked."""
        test_cases = [
            "http://localhost/image.jpg",
            "https://localhost/image.jpg",
            "http://127.0.0.1/image.jpg",
        ]
        for url in test_cases:
            is_valid, error = validate_image_url(url)
            assert is_valid is False
            assert "localhost" in error.lower() or "not allowed" in error.lower()

    def test_private_ip_blocked(self):
        """Test that private IP ranges are blocked."""
        test_cases = [
            "http://192.168.1.1/image.jpg",
            "https://10.0.0.1/image.jpg",
            "http://172.16.0.1/image.jpg",
        ]
        for url in test_cases:
            is_valid, error = validate_image_url(url)
            assert is_valid is False
            assert "private" in error.lower() or "not allowed" in error.lower()

    def test_invalid_scheme_blocked(self):
        """Test that non-HTTP/HTTPS schemes are blocked."""
        test_cases = [
            "ftp://example.com/image.jpg",
            "file:///path/to/image.jpg",
        ]
        for url in test_cases:
            is_valid, error = validate_image_url(url)
            assert is_valid is False
            assert "scheme" in error.lower() or "http" in error.lower()


class TestRequireTokenValidation:
    """Tests for require_token_validation function."""

    def test_valid_token_passes(self):
        """Test that matching tokens pass validation."""
        verify_token = "secret_token_123"
        inbound_token = "secret_token_123"
        require_token_validation(verify_token, inbound_token)

    def test_mismatched_token_raises_401(self):
        """Test that mismatched tokens raise HTTPException 401."""
        verify_token = "secret_token_123"
        inbound_token = "wrong_token"
        with pytest.raises(HTTPException) as exc_info:
            require_token_validation(verify_token, inbound_token)
        assert exc_info.value.status_code == 401
        assert "Invalid token" in exc_info.value.detail

    def test_empty_verify_token_raises_503(self):
        """Test that empty verify_token raises HTTPException 503."""
        verify_token = ""
        inbound_token = "any_token"
        with pytest.raises(HTTPException) as exc_info:
            require_token_validation(verify_token, inbound_token)
        assert exc_info.value.status_code == 503
        assert "not configured" in exc_info.value.detail.lower()