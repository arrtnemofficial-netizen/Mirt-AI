"""Security utilities for authentication and input validation.

This module provides secure functions for:
- Token comparison (timing-safe)
- Image URL validation (SSRF protection)
- Token validation helpers
"""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlparse

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Maximum URL length to prevent DoS
MAX_URL_LENGTH = 2048

# Private IP ranges that should be blocked
PRIVATE_IP_PREFIXES = [
    "127.",
    "192.168.",
    "10.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
]


def secure_token_compare(token1: str, token2: str) -> bool:
    """Compare two tokens in a timing-safe manner.

    Uses secrets.compare_digest() to prevent timing attacks that could
    allow an attacker to determine the correct token by measuring response times.

    Args:
        token1: First token to compare
        token2: Second token to compare

    Returns:
        True if tokens match, False otherwise
    """
    if not token1 or not token2:
        return False
    return secrets.compare_digest(token1, token2)


def validate_image_url(url: str) -> tuple[bool, str | None]:
    """Validate image URL to prevent SSRF (Server-Side Request Forgery) attacks.

    Blocks:
    - URLs with non-HTTP/HTTPS schemes
    - URLs pointing to localhost or private IP ranges
    - URLs exceeding maximum length

    Args:
        url: URL to validate

    Returns:
        Tuple of (is_valid, error_message). If is_valid is False, error_message
        contains the reason. If is_valid is True, error_message is None.
    """
    if not url or not isinstance(url, str):
        return False, "URL is required and must be a string"

    # Check length
    if len(url) > MAX_URL_LENGTH:
        return False, f"URL exceeds maximum length of {MAX_URL_LENGTH} characters"

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL format: {e}"

    # Check scheme
    if parsed.scheme not in ("http", "https"):
        return False, f"URL scheme must be http or https, got: {parsed.scheme}"

    # Check hostname
    hostname = parsed.hostname
    if not hostname:
        return False, "URL must have a hostname"

    hostname_lower = hostname.lower()

    # Block localhost variations
    if hostname_lower in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False, "URLs pointing to localhost are not allowed"

    # Block private IP ranges
    for prefix in PRIVATE_IP_PREFIXES:
        if hostname_lower.startswith(prefix):
            return False, "URLs pointing to private IP ranges are not allowed"

    # Additional check: block IPv4 private ranges (172.16.0.0 - 172.31.255.255)
    # This is already covered by prefix check, but explicit for clarity
    if hostname_lower.startswith("172."):
        parts = hostname_lower.split(".")
        if len(parts) >= 2:
            try:
                second_octet = int(parts[1])
                if 16 <= second_octet <= 31:
                    return False, "URLs pointing to private IP ranges (172.16-31.x.x) are not allowed"
            except (ValueError, IndexError):
                pass

    return True, None


def require_token_validation(verify_token: str, inbound_token: str | None) -> None:
    """Validate webhook token and raise HTTPException if invalid.

    This function enforces that:
    1. verify_token must be configured (non-empty)
    2. inbound_token must match verify_token exactly (timing-safe comparison)

    Args:
        verify_token: Expected token from configuration
        inbound_token: Token from incoming request (header or query param)

    Raises:
        HTTPException: 503 if verify_token is not configured
        HTTPException: 401 if tokens don't match
    """
    # Require that verify_token is configured
    if not verify_token or not verify_token.strip():
        logger.error("[SECURITY] Token validation required but verify_token is not configured")
        raise HTTPException(
            status_code=503,
            detail="Webhook authentication not configured. Please set MANYCHAT_VERIFY_TOKEN.",
        )

    # Normalize inbound_token (handle None, empty string, whitespace)
    inbound = (inbound_token or "").strip()

    # Compare tokens using timing-safe comparison
    if not secure_token_compare(verify_token, inbound):
        logger.warning("[SECURITY] Token validation failed - tokens do not match")
        raise HTTPException(status_code=401, detail="Invalid token")