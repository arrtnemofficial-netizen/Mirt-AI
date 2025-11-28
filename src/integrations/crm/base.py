"""Base CRM client interface.

This module defines the abstract interface for CRM integrations.
All CRM clients (Snitkix, etc.) should implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from src.services.order_model import Order, OrderStatus


class CRMErrorType(str, Enum):
    """Types of CRM errors."""

    CONNECTION = "connection"
    AUTHENTICATION = "authentication"
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    UNKNOWN = "unknown"


@dataclass
class CRMResponse:
    """Standard response from CRM operations."""

    success: bool
    order_id: str | None = None  # CRM-assigned order ID
    data: dict[str, Any] | None = None
    error: str | None = None
    error_type: CRMErrorType | None = None

    @classmethod
    def ok(cls, order_id: str, data: dict[str, Any] | None = None) -> CRMResponse:
        return cls(success=True, order_id=order_id, data=data)

    @classmethod
    def fail(cls, error: str, error_type: CRMErrorType = CRMErrorType.UNKNOWN) -> CRMResponse:
        return cls(success=False, error=error, error_type=error_type)


class BaseCRMClient(ABC):
    """Abstract base class for CRM clients.

    All CRM integrations should implement this interface to ensure
    consistent behavior across different CRM systems.
    """

    @abstractmethod
    async def create_order(self, order: Order) -> CRMResponse:
        """Create a new order in the CRM.

        Args:
            order: Order model with all required data

        Returns:
            CRMResponse with success status and CRM order ID
        """
        pass

    @abstractmethod
    async def update_order_status(
        self,
        order_id: str,
        status: OrderStatus,
        notes: str | None = None,
    ) -> CRMResponse:
        """Update order status in the CRM.

        Args:
            order_id: CRM order ID
            status: New order status
            notes: Optional notes for the status update

        Returns:
            CRMResponse with success status
        """
        pass

    @abstractmethod
    async def get_order(self, order_id: str) -> CRMResponse:
        """Get order details from CRM.

        Args:
            order_id: CRM order ID

        Returns:
            CRMResponse with order data
        """
        pass

    @abstractmethod
    async def search_orders(
        self,
        phone: str | None = None,
        email: str | None = None,
        external_id: str | None = None,
        status: OrderStatus | None = None,
        limit: int = 10,
    ) -> CRMResponse:
        """Search orders in CRM.

        Args:
            phone: Customer phone number
            email: Customer email
            external_id: External order ID
            status: Filter by status
            limit: Maximum number of results

        Returns:
            CRMResponse with list of orders
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if CRM connection is healthy.

        Returns:
            True if CRM is accessible, False otherwise
        """
        pass

    # Optional methods with default implementations

    async def add_order_note(self, order_id: str, note: str) -> CRMResponse:
        """Add a note to an existing order.

        Default implementation returns not implemented error.
        Override in subclass if CRM supports this.
        """
        return CRMResponse.fail(
            "add_order_note not implemented for this CRM",
            CRMErrorType.UNKNOWN,
        )

    async def get_customer(self, phone: str) -> CRMResponse:
        """Get customer by phone number.

        Default implementation returns not implemented error.
        Override in subclass if CRM supports this.
        """
        return CRMResponse.fail(
            "get_customer not implemented for this CRM",
            CRMErrorType.UNKNOWN,
        )

    async def create_customer(
        self,
        full_name: str,
        phone: str,
        email: str | None = None,
        **extra_fields,
    ) -> CRMResponse:
        """Create a new customer in CRM.

        Default implementation returns not implemented error.
        Override in subclass if CRM supports this.
        """
        return CRMResponse.fail(
            "create_customer not implemented for this CRM",
            CRMErrorType.UNKNOWN,
        )
