"""Custom exceptions for Celery workers.

These exceptions control retry behavior:
- RetryableError: Will be retried with exponential backoff
- PermanentError: Will NOT be retried (business logic failure)
- RateLimitError: Will be retried with longer delay
"""

from __future__ import annotations


class WorkerError(Exception):
    """Base exception for all worker errors."""

    pass


class RetryableError(WorkerError):
    """Error that should be retried.

    Use for transient failures:
    - Network timeouts
    - Database connection issues
    - External API temporary failures
    """

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


class PermanentError(WorkerError):
    """Error that should NOT be retried.

    Use for business logic failures:
    - Invalid input data
    - Resource not found
    - Authorization failures
    - Validation errors
    """

    def __init__(self, message: str, error_code: str | None = None):
        super().__init__(message)
        self.error_code = error_code


class RateLimitError(RetryableError):
    """Rate limit hit - retry with longer delay.

    Use when external API returns 429 or similar.
    """

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class ExternalServiceError(RetryableError):
    """External service unavailable.

    Use for CRM, LLM, or other external API failures.
    """

    def __init__(self, service: str, message: str, status_code: int | None = None):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.status_code = status_code


class DatabaseError(RetryableError):
    """Database operation failed.

    Use for Supabase connection/query failures.
    """

    pass


class IdempotencyError(PermanentError):
    """Task already processed (duplicate).

    Use when task_id was already completed.
    """

    def __init__(self, task_id: str):
        super().__init__(f"Task {task_id} already processed", error_code="DUPLICATE")
        self.task_id = task_id
