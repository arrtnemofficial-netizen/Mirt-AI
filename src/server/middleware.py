"""FastAPI middleware for rate limiting and request processing.

This module provides distributed rate limiting using Redis for multi-instance
deployments, with fallback to in-memory limiter if Redis is unavailable.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request, Response
    from starlette.types import ASGIApp


logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_size: int = 10
    enabled: bool = True

    # Paths excluded from rate limiting
    excluded_paths: list[str] = field(default_factory=lambda: ["/health", "/docs", "/openapi.json"])


@dataclass
class ClientState:
    """Track request state for a single client."""

    minute_requests: int = 0
    hour_requests: int = 0
    minute_start: float = 0.0
    hour_start: float = 0.0
    last_request: float = 0.0


class InMemoryRateLimiter:
    """Simple in-memory rate limiter with sliding window."""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._clients: dict[str, ClientState] = defaultdict(ClientState)

    def _get_client_key(self, request: Request) -> str:
        """Extract client identifier from request."""
        # Try X-Forwarded-For for proxied requests
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

        # Try X-Real-IP
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        if request.client:
            return request.client.host

        return "unknown"

    def _reset_windows(self, state: ClientState, now: float) -> None:
        """Reset rate limit windows if they've expired."""
        # Reset minute window
        if now - state.minute_start >= 60:
            state.minute_requests = 0
            state.minute_start = now

        # Reset hour window
        if now - state.hour_start >= 3600:
            state.hour_requests = 0
            state.hour_start = now

    def check_rate_limit(self, request: Request) -> tuple[bool, str | None, int | None]:
        """Check if request is within rate limits.

        Returns:
            Tuple of (allowed, error_message, retry_after_seconds)
        """
        if not self.config.enabled:
            return True, None, None

        # Skip excluded paths
        if request.url.path in self.config.excluded_paths:
            return True, None, None

        client_key = self._get_client_key(request)
        state = self._clients[client_key]
        now = time.time()

        # Initialize windows on first request
        if state.minute_start == 0:
            state.minute_start = now
            state.hour_start = now

        self._reset_windows(state, now)

        # Check minute limit
        if state.minute_requests >= self.config.requests_per_minute:
            retry_after = int(60 - (now - state.minute_start)) + 1
            logger.warning(
                "Rate limit exceeded for %s: %d requests/minute",
                client_key,
                state.minute_requests,
            )
            return False, "Rate limit exceeded. Please slow down.", retry_after

        # Check hour limit
        if state.hour_requests >= self.config.requests_per_hour:
            retry_after = int(3600 - (now - state.hour_start)) + 1
            logger.warning(
                "Hourly rate limit exceeded for %s: %d requests/hour",
                client_key,
                state.hour_requests,
            )
            return False, "Hourly rate limit exceeded. Please try again later.", retry_after

        # Update counters
        state.minute_requests += 1
        state.hour_requests += 1
        state.last_request = now

        return True, None, None

    def cleanup_old_clients(self, max_age_hours: int = 24) -> int:
        """Remove stale client entries to prevent memory leaks."""
        now = time.time()
        max_age_seconds = max_age_hours * 3600
        to_remove = []

        for client_key, state in self._clients.items():
            if now - state.last_request > max_age_seconds:
                to_remove.append(client_key)

        for key in to_remove:
            del self._clients[key]

        if to_remove:
            logger.debug("Cleaned up %d stale rate limit entries", len(to_remove))

        return len(to_remove)


class RedisRateLimiter:
    """Redis-based distributed rate limiter."""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._redis_client = None
        self._use_redis = False
        self._init_redis()

    def _init_redis(self):
        """Initialize Redis client if available."""
        try:
            import os

            import redis

            from src.conf.config import settings

            redis_url = os.getenv("REDIS_URL") or settings.REDIS_URL
            if not redis_url:
                logger.debug("No REDIS_URL configured, using in-memory fallback")
                return

            self._redis_client = redis.from_url(redis_url, decode_responses=True)
            self._redis_client.ping()  # Test connection
            self._use_redis = True
            logger.info("Using Redis for distributed rate limiting")
        except Exception as e:
            logger.warning("Redis not available for rate limiting, using in-memory fallback: %s", e)
            self._redis_client = None
            self._use_redis = False

    def _get_client_key(self, request: Request) -> str:
        """Extract client identifier from request."""
        # Try X-Forwarded-For for proxied requests
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

        # Try X-Real-IP
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        if request.client:
            return request.client.host

        return "unknown"

    def check_rate_limit(self, request: Request) -> tuple[bool, str | None, int | None]:
        """Check if request is within rate limits using Redis or in-memory fallback."""
        if not self.config.enabled:
            return True, None, None

        # Skip excluded paths
        if request.url.path in self.config.excluded_paths:
            return True, None, None

        client_key = self._get_client_key(request)

        if self._use_redis and self._redis_client:
            return self._check_redis_rate_limit(client_key)
        else:
            # Fallback to in-memory (will be handled by InMemoryRateLimiter)
            return True, None, None

    def _check_redis_rate_limit(self, client_key: str) -> tuple[bool, str | None, int | None]:
        """Check rate limit using Redis sliding window."""
        try:
            import time

            now = time.time()
            minute_key = f"rate_limit:minute:{client_key}"
            hour_key = f"rate_limit:hour:{client_key}"

            pipe = self._redis_client.pipeline()

            # Minute window
            pipe.zremrangebyscore(minute_key, 0, now - 60)
            pipe.zcard(minute_key)
            pipe.zadd(minute_key, {str(now): now})
            pipe.expire(minute_key, 60)

            # Hour window
            pipe.zremrangebyscore(hour_key, 0, now - 3600)
            pipe.zcard(hour_key)
            pipe.zadd(hour_key, {str(now): now})
            pipe.expire(hour_key, 3600)

            results = pipe.execute()

            minute_count = results[1]
            hour_count = results[4]

            # Check limits
            if minute_count >= self.config.requests_per_minute:
                retry_after = 60
                logger.warning(
                    "Rate limit exceeded (minute) for %s: %d/%d requests",
                    client_key,
                    minute_count,
                    self.config.requests_per_minute,
                )
                return False, "Rate limit exceeded. Please slow down.", retry_after

            if hour_count >= self.config.requests_per_hour:
                retry_after = 3600
                logger.warning(
                    "Rate limit exceeded (hour) for %s: %d/%d requests",
                    client_key,
                    hour_count,
                    self.config.requests_per_hour,
                )
                return False, "Hourly rate limit exceeded. Please try again later.", retry_after

            return True, None, None

        except Exception as e:
            logger.error("Redis rate limit check failed: %s", e)
            # Fail open: allow request if Redis check fails
            return True, None, None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that applies rate limiting to incoming requests.

    Uses Redis for distributed rate limiting with in-memory fallback.
    """

    def __init__(self, app: ASGIApp, config: RateLimitConfig | None = None):
        super().__init__(app)
        self.config = config or RateLimitConfig()
        self.redis_limiter = RedisRateLimiter(self.config)
        self.memory_limiter = InMemoryRateLimiter(self.config)
        self._use_redis = self.redis_limiter._use_redis
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600  # Run cleanup every hour

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with rate limiting."""
        # Periodic cleanup for in-memory limiter
        if not self._use_redis:
            now = time.time()
            if now - self._last_cleanup > self._cleanup_interval:
                self.memory_limiter.cleanup_old_clients()
                self._last_cleanup = now

        # Check rate limit (Redis first, fallback to memory)
        if self._use_redis:
            allowed, error_message, retry_after = self.redis_limiter.check_rate_limit(request)
        else:
            allowed, error_message, retry_after = self.memory_limiter.check_rate_limit(request)

        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": error_message,
                    "retry_after": retry_after,
                },
            )
            if retry_after:
                response.headers["Retry-After"] = str(retry_after)
            return response

        # Process request
        response = await call_next(request)
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging incoming requests and responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response details."""
        start_time = time.time()

        # Extract request info
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log 404 errors with additional details
        if response.status_code == 404:
            from src.core.logging import log_with_root_cause

            log_with_root_cause(
                logger,
                "warning",
                f"[404_NOT_FOUND] {method} {path} {response.status_code} {duration_ms:.2f}ms client={client_ip}",
                root_cause="ENDPOINT_NOT_FOUND",
                method=method,
                path=path,
                status_code=404,
                duration_ms=duration_ms,
                client_ip=client_ip,
                query=str(request.url.query),
            )
        else:
            # Log request
            logger.info(
                "%s %s %d %.2fms client=%s",
                method,
                path,
                response.status_code,
                duration_ms,
                client_ip,
            )

        return response


def setup_middleware(app, *, enable_rate_limit: bool = True, enable_logging: bool = True) -> None:
    """Configure all middleware for the FastAPI application."""
    if enable_logging:
        app.add_middleware(RequestLoggingMiddleware)

    if enable_rate_limit:
        config = RateLimitConfig(
            requests_per_minute=60,
            requests_per_hour=1000,
            burst_size=10,
            excluded_paths=[
                "/health",
                "/docs",
                "/openapi.json",
                "/webhooks/manychat",
                "/webhooks/manychat/",
                "/api/v1/messages",
                "/api/v1/messages/",
                "/webhooks/snitkix",
                "/webhooks/snitkix/",
            ],
        )
        app.add_middleware(RateLimitMiddleware, config=config)
