"""Snitkix CRM client implementation.

Snitkix CRM API integration for order management.
Documentation: https://help.snitkix.com/api

Environment variables required:
- SNITKIX_API_URL: Base URL for Snitkix API
- SNITKIX_API_KEY: API key for authentication
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from src.conf.config import settings
from src.integrations.crm.base import BaseCRMClient, CRMErrorType, CRMResponse
from src.services.data.order_model import Order, OrderStatus


@dataclass
class OrderStatusResult:
    """Result of order status query."""

    order_id: str
    status: str
    snitkix_status: str
    updated_at: str | None = None


logger = logging.getLogger(__name__)


from src.conf.crm_config import SNITKIX_STATUS_TITLES as STATUS_MAPPING, REVERSE_SNITKIX_STATUS as REVERSE_STATUS_MAPPING


class SnitkixCRMClient(BaseCRMClient):
    """Snitkix CRM API client.

    Usage:
        client = SnitkixCRMClient()
        response = await client.create_order(order)
        if response.success:
            print(f"Order created: {response.order_id}")
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        """Initialize Snitkix client.

        Args:
            api_url: Snitkix API base URL (default from settings)
            api_key: Snitkix API key (default from settings)
            timeout: Request timeout in seconds
        """
        self.api_url = (api_url or getattr(settings, "SNITKIX_API_URL", "")).rstrip("/")
        self.api_key = api_key or getattr(settings, "SNITKIX_API_KEY", "")
        self.timeout = timeout

        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.aclose()

    def _handle_error(self, response: httpx.Response) -> CRMResponse:
        """Convert HTTP error to CRMResponse."""
        status = response.status_code

        try:
            data = response.json()
            error_msg = data.get("message") or data.get("error") or str(data)
        except Exception:
            error_msg = response.text or f"HTTP {status}"

        if status == 401:
            return CRMResponse.fail(error_msg, CRMErrorType.AUTHENTICATION)
        elif status == 404:
            return CRMResponse.fail(error_msg, CRMErrorType.NOT_FOUND)
        elif status == 422:
            return CRMResponse.fail(error_msg, CRMErrorType.VALIDATION)
        elif status == 429:
            return CRMResponse.fail(error_msg, CRMErrorType.RATE_LIMIT)
        elif status >= 500:
            return CRMResponse.fail(error_msg, CRMErrorType.SERVER_ERROR)
        else:
            return CRMResponse.fail(error_msg, CRMErrorType.UNKNOWN)

    async def create_order(self, order: Order) -> CRMResponse:
        """Create a new order in Snitkix CRM."""
        if not self.api_url or not self.api_key:
            logger.warning("Snitkix CRM not configured, skipping order creation")
            return CRMResponse.fail(
                "Snitkix CRM not configured",
                CRMErrorType.CONNECTION,
            )

        payload = self._build_order_payload(order)

        try:
            response = await self._client.post("/api/orders", json=payload)

            if response.status_code in (200, 201):
                data = response.json()
                order_id = str(data.get("id") or data.get("order_id") or "")
                logger.info("Snitkix order created: %s", order_id)
                return CRMResponse.ok(order_id, data)
            else:
                return self._handle_error(response)

        except httpx.ConnectError as e:
            logger.error("Snitkix connection error: %s", e)
            return CRMResponse.fail(str(e), CRMErrorType.CONNECTION)
        except httpx.TimeoutException as e:
            logger.error("Snitkix timeout: %s", e)
            return CRMResponse.fail(str(e), CRMErrorType.CONNECTION)
        except Exception as e:
            logger.exception("Snitkix unexpected error: %s", e)
            return CRMResponse.fail(str(e), CRMErrorType.UNKNOWN)

    async def update_order_status(
        self,
        order_id: str,
        status: OrderStatus,
        notes: str | None = None,
    ) -> CRMResponse:
        """Update order status in Snitkix CRM."""
        if not self.api_url or not self.api_key:
            return CRMResponse.fail("Snitkix CRM not configured", CRMErrorType.CONNECTION)

        snitkix_status = STATUS_MAPPING.get(status, "new")
        payload = {"status": snitkix_status}
        if notes:
            payload["notes"] = notes

        try:
            response = await self._client.patch(f"/api/orders/{order_id}", json=payload)

            if response.status_code == 200:
                data = response.json()
                logger.info("Snitkix order %s updated to %s", order_id, status)
                return CRMResponse.ok(order_id, data)
            else:
                return self._handle_error(response)

        except Exception as e:
            logger.exception("Snitkix update error: %s", e)
            return CRMResponse.fail(str(e), CRMErrorType.UNKNOWN)

    async def get_order(self, order_id: str) -> CRMResponse:
        """Get order details from Snitkix CRM."""
        if not self.api_url or not self.api_key:
            return CRMResponse.fail("Snitkix CRM not configured", CRMErrorType.CONNECTION)

        try:
            response = await self._client.get(f"/api/orders/{order_id}")

            if response.status_code == 200:
                data = response.json()
                return CRMResponse.ok(order_id, data)
            else:
                return self._handle_error(response)

        except Exception as e:
            logger.exception("Snitkix get order error: %s", e)
            return CRMResponse.fail(str(e), CRMErrorType.UNKNOWN)

    async def get_order_status(self, order_id: str) -> OrderStatusResult | None:
        """Get order status from Snitkix CRM.

        Args:
            order_id: CRM order ID

        Returns:
            OrderStatusResult with status info, or None if not found
        """
        response = await self.get_order(order_id)

        if not response.success or not response.data:
            return None

        snitkix_status = response.data.get("status", "unknown")
        our_status = REVERSE_STATUS_MAPPING.get(snitkix_status, OrderStatus.NEW)

        return OrderStatusResult(
            order_id=order_id,
            status=our_status.value,
            snitkix_status=snitkix_status,
            updated_at=response.data.get("updated_at"),
        )

    async def search_orders(
        self,
        phone: str | None = None,
        email: str | None = None,
        external_id: str | None = None,
        status: OrderStatus | None = None,
        limit: int = 10,
    ) -> CRMResponse:
        """Search orders in Snitkix CRM."""
        if not self.api_url or not self.api_key:
            return CRMResponse.fail("Snitkix CRM not configured", CRMErrorType.CONNECTION)

        params: dict[str, Any] = {"limit": limit}
        if phone:
            params["phone"] = phone
        if email:
            params["email"] = email
        if external_id:
            params["external_id"] = external_id
        if status:
            params["status"] = STATUS_MAPPING.get(status, "new")

        try:
            response = await self._client.get("/api/orders", params=params)

            if response.status_code == 200:
                data = response.json()
                orders = data.get("data") or data.get("orders") or data
                return CRMResponse.ok(None, {"orders": orders})
            else:
                return self._handle_error(response)

        except Exception as e:
            logger.exception("Snitkix search error: %s", e)
            return CRMResponse.fail(str(e), CRMErrorType.UNKNOWN)

    async def health_check(self) -> bool:
        """Check if Snitkix CRM connection is healthy."""
        if not self.api_url or not self.api_key:
            return False

        try:
            response = await self._client.get("/api/health")
            return response.status_code == 200
        except Exception:
            return False

    async def add_order_note(self, order_id: str, note: str) -> CRMResponse:
        """Add a note to an existing order."""
        if not self.api_url or not self.api_key:
            return CRMResponse.fail("Snitkix CRM not configured", CRMErrorType.CONNECTION)

        try:
            response = await self._client.post(
                f"/api/orders/{order_id}/notes",
                json={"note": note},
            )

            if response.status_code in (200, 201):
                data = response.json()
                return CRMResponse.ok(order_id, data)
            else:
                return self._handle_error(response)

        except Exception as e:
            logger.exception("Snitkix add note error: %s", e)
            return CRMResponse.fail(str(e), CRMErrorType.UNKNOWN)

    async def get_customer(self, phone: str) -> CRMResponse:
        """Get customer by phone number."""
        if not self.api_url or not self.api_key:
            return CRMResponse.fail("Snitkix CRM not configured", CRMErrorType.CONNECTION)

        try:
            response = await self._client.get(
                "/api/customers",
                params={"phone": phone},
            )

            if response.status_code == 200:
                data = response.json()
                customers = data.get("data") or data.get("customers") or []
                if customers:
                    return CRMResponse.ok(None, {"customer": customers[0]})
                return CRMResponse.fail("Customer not found", CRMErrorType.NOT_FOUND)
            else:
                return self._handle_error(response)

        except Exception as e:
            logger.exception("Snitkix get customer error: %s", e)
            return CRMResponse.fail(str(e), CRMErrorType.UNKNOWN)

    def _build_order_payload(self, order: Order) -> dict[str, Any]:
        """Build Snitkix API payload from Order model."""
        return {
            "external_id": order.external_id,
            "source": order.source,
            "source_id": order.source_id,
            # Customer
            "customer": {
                "name": order.customer.full_name,
                "phone": order.customer.phone,
                "email": order.customer.email,
            },
            # Delivery
            "delivery": {
                "method": order.delivery_method.value,
                "city": order.customer.city,
                "address": order.customer.nova_poshta_branch or order.customer.nova_poshta_address,
            },
            # Items
            "items": [
                {
                    "product_id": item.product_id,
                    "sku": item.sku,
                    "name": item.product_name,
                    "size": item.size,
                    "color": item.color,
                    "quantity": item.quantity,
                    "price": item.price,
                }
                for item in order.items
            ],
            # Totals
            "subtotal": order.subtotal,
            "discount": order.discount,
            "delivery_cost": order.delivery_cost,
            "total": order.total,
            # Payment
            "payment_method": order.payment_method.value,
            "status": STATUS_MAPPING.get(order.status, "new"),
            # Notes
            "notes": order.customer_notes,
            "internal_notes": order.internal_notes,
        }


# Singleton instance
_crm_client: SnitkixCRMClient | None = None


def get_snitkix_client() -> SnitkixCRMClient:
    """Get or create Snitkix CRM client singleton."""
    global _crm_client
    if _crm_client is None:
        _crm_client = SnitkixCRMClient()
    return _crm_client
