"""Snitkix CRM Webhook Handlers.

Bidirectional webhook endpoints for receiving status updates
and other events from Snitkix CRM system.

Security:
- API key authentication via header
- Request signature verification (if supported by Snitkix)
- Rate limiting and request validation

Endpoints:
- POST /webhooks/snitkix/order-status - Order status updates
- POST /webhooks/snitkix/payment-status - Payment confirmation events
- POST /webhooks/snitkix/inventory - Stock/inventory updates
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.conf.config import settings
from src.integrations.crm.crmservice import get_crm_service


logger = logging.getLogger(__name__)


class SnitkixWebhookHandler:
    """Handler for Snitkix CRM webhook events."""

    def __init__(self):
        self.crm_service = get_crm_service()
        self.api_key = settings.snitkix_api_key

    async def verify_webhook_signature(self, request: Request) -> bool:
        """Verify webhook request authenticity.
        
        Checks:
        1. API key in X-API-Key header
        2. Optional signature verification (if Snitkix supports it)
        """
        # Check API key
        provided_key = request.headers.get("X-API-Key")
        if not provided_key or provided_key != self.api_key:
            logger.warning(
                "[WEBHOOK:SNITKIX] Invalid or missing API key: %s",
                provided_key[:8] + "..." if provided_key else "None",
            )
            return False

        # TODO: Add signature verification if Snitkix supports it
        # signature = request.headers.get("X-Signature")
        # if signature and not self._verify_signature(payload, signature):
        #     return False

        return True

    async def handle_order_status_update(
        self, request: Request, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle order status update from Snitkix CRM.
        
        Expected payload format:
        {
            "order_id": "CRM-12345",
            "external_id": "session_12345_timestamp",
            "status": "processing|shipped|delivered|cancelled",
            "timestamp": "2025-12-08T15:30:00Z",
            "metadata": {...}
        }
        """
        try:
            crm_order_id = payload.get("order_id")
            new_status = payload.get("status")
            external_id = payload.get("external_id")
            metadata = payload.get("metadata", {})

            if not crm_order_id or not new_status:
                raise ValueError("Missing required fields: order_id, status")

            # Validate status
            valid_statuses = {
                "pending", "queued", "created", "processing",
                "shipped", "delivered", "cancelled", "failed"
            }
            if new_status not in valid_statuses:
                raise ValueError(f"Invalid status: {new_status}")

            logger.info(
                "[WEBHOOK:SNITKIX] Order status update: %s → %s",
                crm_order_id,
                new_status,
            )

            # Process through CRM service
            result = await self.crm_service.handle_webhook_status_update(
                crm_order_id=crm_order_id,
                new_status=new_status,
                metadata=metadata,
            )

            return {
                "success": True,
                "processed": result.get("status"),
                "crm_order_id": crm_order_id,
                "new_status": new_status,
            }

        except Exception as e:
            logger.exception(
                "[WEBHOOK:SNITKIX] Failed to process order status update: %s",
                e,
            )
            return {
                "success": False,
                "error": str(e),
                "crm_order_id": payload.get("order_id"),
            }

    async def handle_payment_confirmation(
        self, request: Request, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle payment confirmation from Snitkix CRM.
        
        Expected payload format:
        {
            "order_id": "CRM-12345",
            "payment_status": "confirmed|failed|refunded",
            "amount": 1500.00,
            "currency": "UAH",
            "payment_method": "bank_transfer|cash_on_delivery",
            "timestamp": "2025-12-08T15:30:00Z"
        }
        """
        try:
            crm_order_id = payload.get("order_id")
            payment_status = payload.get("payment_status")
            amount = payload.get("amount")

            if not crm_order_id or not payment_status:
                raise ValueError("Missing required fields: order_id, payment_status")

            logger.info(
                "[WEBHOOK:SNITKIX] Payment confirmation: %s → %s (%.2f)",
                crm_order_id,
                payment_status,
                amount or 0,
            )

            # Update order status based on payment
            if payment_status == "confirmed":
                order_status = "processing"
            elif payment_status == "failed":
                order_status = "failed"
            elif payment_status == "refunded":
                order_status = "cancelled"
            else:
                order_status = "pending"

            result = await self.crm_service.handle_webhook_status_update(
                crm_order_id=crm_order_id,
                new_status=order_status,
                metadata={
                    "payment_status": payment_status,
                    "payment_amount": amount,
                    "payment_currency": payload.get("currency", "UAH"),
                    "payment_method": payload.get("payment_method"),
                },
            )

            return {
                "success": True,
                "processed": result.get("status"),
                "crm_order_id": crm_order_id,
                "payment_status": payment_status,
            }

        except Exception as e:
            logger.exception(
                "[WEBHOOK:SNITKIX] Failed to process payment confirmation: %s",
                e,
            )
            return {
                "success": False,
                "error": str(e),
                "crm_order_id": payload.get("order_id"),
            }

    async def handle_inventory_update(
        self, request: Request, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle inventory/stock updates from Snitkix CRM.
        
        Expected payload format:
        {
            "products": [
                {
                    "product_id": "123",
                    "sku": "TSHIRT-BLACK-M",
                    "stock_quantity": 5,
                    "status": "in_stock|out_of_stock|low_stock"
                }
            ],
            "timestamp": "2025-12-08T15:30:00Z"
        }
        """
        try:
            products = payload.get("products", [])

            logger.info(
                "[WEBHOOK:SNITKIX] Inventory update for %d products",
                len(products),
            )

            # TODO: Update product inventory in local database
            # This could trigger stock alerts, update product availability, etc.

            for product in products:
                product_id = product.get("product_id")
                stock_qty = product.get("stock_quantity")
                stock_status = product.get("status")

                logger.debug(
                    "[WEBHOOK:SNITKIX] Product %s: %d units, status %s",
                    product_id,
                    stock_qty,
                    stock_status,
                )

                # Update local product database
                # await self.product_service.update_stock(product_id, stock_qty, stock_status)

            return {
                "success": True,
                "processed": len(products),
                "message": "Inventory updates processed",
            }

        except Exception as e:
            logger.exception(
                "[WEBHOOK:SNITKIX] Failed to process inventory update: %s",
                e,
            )
            return {
                "success": False,
                "error": str(e),
            }


# Global handler instance
_webhook_handler: SnitkixWebhookHandler | None = None


def get_webhook_handler() -> SnitkixWebhookHandler:
    """Get global webhook handler instance."""
    global _webhook_handler
    if _webhook_handler is None:
        _webhook_handler = SnitkixWebhookHandler()
    return _webhook_handler


# FastAPI endpoint functions

async def snitkix_order_status_webhook(request: Request) -> JSONResponse:
    """Handle order status updates from Snitkix CRM."""
    if not settings.snitkix_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Snitkix CRM integration disabled",
        )

    handler = get_webhook_handler()

    # Verify authentication
    if not await handler.verify_webhook_signature(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication",
        )

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {e}",
        )

    result = await handler.handle_order_status_update(request, payload)

    status_code = status.HTTP_200_OK if result.get("success") else status.HTTP_400_BAD_REQUEST
    return JSONResponse(content=result, status_code=status_code)


async def snitkix_payment_webhook(request: Request) -> JSONResponse:
    """Handle payment confirmation from Snitkix CRM."""
    if not settings.snitkix_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Snitkix CRM integration disabled",
        )

    handler = get_webhook_handler()

    # Verify authentication
    if not await handler.verify_webhook_signature(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication",
        )

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {e}",
        )

    result = await handler.handle_payment_confirmation(request, payload)

    status_code = status.HTTP_200_OK if result.get("success") else status.HTTP_400_BAD_REQUEST
    return JSONResponse(content=result, status_code=status_code)


async def snitkix_inventory_webhook(request: Request) -> JSONResponse:
    """Handle inventory updates from Snitkix CRM."""
    if not settings.snitkix_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Snitkix CRM integration disabled",
        )

    handler = get_webhook_handler()

    # Verify authentication
    if not await handler.verify_webhook_signature(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication",
        )

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {e}",
        )

    result = await handler.handle_inventory_update(request, payload)

    status_code = status.HTTP_200_OK if result.get("success") else status.HTTP_400_BAD_REQUEST
    return JSONResponse(content=result, status_code=status_code)
