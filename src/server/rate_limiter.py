"""
Rate Limiter Middleware for FastAPI.
=====================================
Implements SlowAPI-based rate limiting to protect against abuse.
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import FastAPI, Request, Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.conf.config import settings


logger = logging.getLogger(__name__)


def get_api_key_or_ip(request: Request) -> str:
    """Get rate limit key from API key header or IP address.
    
    Priority:
    1. X-API-Key header (for authenticated clients)
    2. Authorization Bearer token (first 16 chars)
    3. Client IP address
    """
    # Check for API key header
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"apikey:{api_key[:16]}"
    
    # Check for Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:23]  # First 16 chars of token
        return f"bearer:{token}"
    
    # Fallback to IP
    return get_remote_address(request)


# =============================================================================
# RATE LIMITS CONFIGURATION
# =============================================================================

# Default limits (can be overridden per-endpoint)
DEFAULT_LIMITS = [
    "100/minute",   # Base limit for most endpoints
    "1000/hour",    # Hourly cap
]

# Stricter limits for expensive operations
LLM_LIMITS = [
    "20/minute",    # LLM calls are expensive
    "200/hour",     # Hourly cap for LLM
]

# Very strict limits for auth/sensitive operations
AUTH_LIMITS = [
    "5/minute",     # Prevent brute force
    "30/hour",      # Hourly cap
]

# Webhook limits (more generous for upstream services)
WEBHOOK_LIMITS = [
    "200/minute",   # Allow burst from webhook providers
    "5000/hour",    # High hourly cap for busy periods
]


# =============================================================================
# LIMITER INSTANCE
# =============================================================================

limiter = Limiter(
    key_func=get_api_key_or_ip,
    default_limits=DEFAULT_LIMITS,
    storage_uri=settings.REDIS_URL if settings.CELERY_ENABLED else None,
    strategy="fixed-window",
    headers_enabled=True,  # Add X-RateLimit-* headers
)


def setup_rate_limiter(app: FastAPI) -> None:
    """Configure rate limiter for FastAPI application.
    
    Args:
        app: FastAPI application instance
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    
    logger.info(
        "[RATE_LIMITER] Initialized with storage=%s",
        "redis" if settings.CELERY_ENABLED else "memory",
    )


# =============================================================================
# DECORATOR HELPERS
# =============================================================================

def limit_llm(func: Callable) -> Callable:
    """Apply LLM-specific rate limits to endpoint."""
    return limiter.limit(LLM_LIMITS[0])(limiter.limit(LLM_LIMITS[1])(func))


def limit_auth(func: Callable) -> Callable:
    """Apply auth-specific rate limits to endpoint."""
    return limiter.limit(AUTH_LIMITS[0])(limiter.limit(AUTH_LIMITS[1])(func))


def limit_webhook(func: Callable) -> Callable:
    """Apply webhook-specific rate limits to endpoint."""
    return limiter.limit(WEBHOOK_LIMITS[0])(limiter.limit(WEBHOOK_LIMITS[1])(func))
