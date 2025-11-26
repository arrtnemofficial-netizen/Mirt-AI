"""Input validation utilities for security and data integrity.

This module provides validators for common input types to prevent
SQL injection, XSS, and other security issues.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse


class ValidationError(ValueError):
    """Raised when input validation fails."""
    pass


# Patterns for dangerous SQL characters
SQL_INJECTION_PATTERN = re.compile(
    r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE|EXEC|EXECUTE)\b|"
    r"['\";]|--|\*/|/\*)",
    re.IGNORECASE,
)

# Pattern for valid product IDs (alphanumeric with optional dashes)
PRODUCT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Pattern for valid session IDs
SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

# Allowed URL schemes
ALLOWED_URL_SCHEMES = {"http", "https"}

# Allowed image domains (can be extended via config)
ALLOWED_IMAGE_DOMAINS = {
    "supabase.co",
    "supabase.in",
    "storage.googleapis.com",
    "cloudinary.com",
    "res.cloudinary.com",
    "images.unsplash.com",
    "mirt.ua",
    "cdn.mirt.ua",
}


def validate_product_id(product_id: str) -> str:
    """Validate and sanitize a product ID.

    Args:
        product_id: The product ID to validate

    Returns:
        The validated product ID (stripped)

    Raises:
        ValidationError: If the product ID is invalid
    """
    if not product_id:
        raise ValidationError("Product ID cannot be empty")

    cleaned = str(product_id).strip()

    if len(cleaned) > 64:
        raise ValidationError("Product ID too long (max 64 characters)")

    if not PRODUCT_ID_PATTERN.match(cleaned):
        raise ValidationError("Product ID contains invalid characters")

    return cleaned


def validate_session_id(session_id: str) -> str:
    """Validate and sanitize a session ID.

    Args:
        session_id: The session ID to validate

    Returns:
        The validated session ID

    Raises:
        ValidationError: If the session ID is invalid
    """
    if not session_id:
        raise ValidationError("Session ID cannot be empty")

    cleaned = str(session_id).strip()

    if not SESSION_ID_PATTERN.match(cleaned):
        raise ValidationError("Session ID contains invalid characters or is too long")

    return cleaned


def validate_url(url: str, *, allow_any_domain: bool = False) -> str:
    """Validate and sanitize a URL.

    Args:
        url: The URL to validate
        allow_any_domain: If False, only allow URLs from ALLOWED_IMAGE_DOMAINS

    Returns:
        The validated URL

    Raises:
        ValidationError: If the URL is invalid or from an untrusted domain
    """
    if not url:
        raise ValidationError("URL cannot be empty")

    cleaned = str(url).strip()

    # Basic length check
    if len(cleaned) > 2048:
        raise ValidationError("URL too long (max 2048 characters)")

    # Parse URL
    try:
        parsed = urlparse(cleaned)
    except Exception as e:
        raise ValidationError(f"Invalid URL format: {e}")

    # Check scheme
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise ValidationError(f"Invalid URL scheme: {parsed.scheme}")

    # Check for host
    if not parsed.netloc:
        raise ValidationError("URL must have a host")

    # Check domain if restricted
    if not allow_any_domain:
        host = parsed.netloc.lower()
        # Check if host ends with any allowed domain
        if not any(host == domain or host.endswith(f".{domain}") for domain in ALLOWED_IMAGE_DOMAINS):
            raise ValidationError(f"URL domain not allowed: {host}")

    return cleaned


def sanitize_search_query(query: str, *, max_length: int = 500) -> str:
    """Sanitize a search query for safe database use.

    Args:
        query: The search query to sanitize
        max_length: Maximum allowed length

    Returns:
        The sanitized query
    """
    if not query:
        return ""

    cleaned = str(query).strip()

    # Truncate
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]

    # Remove potential SQL injection patterns (log but don't fail)
    if SQL_INJECTION_PATTERN.search(cleaned):
        # Replace dangerous patterns with spaces
        cleaned = SQL_INJECTION_PATTERN.sub(" ", cleaned)
        # Clean up multiple spaces
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


def validate_match_count(count: int, *, min_val: int = 1, max_val: int = 50) -> int:
    """Validate a match count parameter.

    Args:
        count: The count to validate
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        The validated count (clamped to range)
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        return min_val

    return max(min_val, min(count, max_val))


def escape_like_pattern(pattern: str) -> str:
    """Escape special characters for SQL LIKE/ILIKE patterns.

    This prevents pattern injection attacks where user input
    could match unintended rows.

    Args:
        pattern: The pattern to escape

    Returns:
        The escaped pattern safe for LIKE queries
    """
    if not pattern:
        return ""

    # Escape special LIKE characters
    escaped = pattern.replace("\\", "\\\\")  # Escape backslash first
    escaped = escaped.replace("%", "\\%")
    escaped = escaped.replace("_", "\\_")

    return escaped
