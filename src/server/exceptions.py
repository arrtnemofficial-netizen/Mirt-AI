"""Custom exception classes for API error handling."""

from __future__ import annotations


class APIError(Exception):
    """Base exception for API errors."""

    def __init__(self, message: str, status_code: int = 400, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail or message


class ValidationError(APIError):
    """Raised when request validation fails."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message, status_code=400, detail=detail)


class AuthenticationError(APIError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed", detail: str | None = None):
        super().__init__(message, status_code=401, detail=detail)


class RateLimitError(APIError):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int | None = None):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class ExternalServiceError(APIError):
    """Raised when external service call fails."""

    def __init__(self, service: str, message: str, status_code: int = 502):
        super().__init__(f"{service} error: {message}", status_code=status_code)
        self.service = service

