"""
Service Exceptions - Production error handling.
===============================================
Custom exceptions for proper error propagation instead of silent failures.
"""

from __future__ import annotations


class ServiceUnavailableError(Exception):
    """Raised when an external service (DB, API) is unavailable."""
    
    def __init__(self, service_name: str, message: str | None = None):
        self.service_name = service_name
        self.message = message or f"{service_name} is unavailable"
        super().__init__(self.message)


class CatalogUnavailableError(ServiceUnavailableError):
    """Raised when catalog/database is unavailable."""
    
    def __init__(self, message: str | None = None):
        super().__init__("catalog", message or "Product catalog is temporarily unavailable")


class OrderCreationError(Exception):
    """Raised when order creation fails."""
    
    def __init__(self, reason: str, session_id: str | None = None):
        self.reason = reason
        self.session_id = session_id
        super().__init__(f"Order creation failed: {reason}")


class DuplicateOrderError(OrderCreationError):
    """Raised when attempting to create a duplicate order."""
    
    def __init__(self, session_id: str, existing_order_id: str | None = None):
        self.existing_order_id = existing_order_id
        super().__init__(
            f"Duplicate order for session {session_id}",
            session_id=session_id,
        )


class ImageValidationError(Exception):
    """Raised when image URL validation fails."""
    
    def __init__(self, url: str, reason: str):
        self.url = url
        self.reason = reason
        super().__init__(f"Invalid image URL: {reason}")
