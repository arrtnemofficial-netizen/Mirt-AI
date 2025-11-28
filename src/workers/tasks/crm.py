"""CRM background tasks.

These tasks handle:
- Creating orders in Snitkix CRM
- Retrying failed order submissions
- Syncing order status

Uses sync_utils to properly call async CRM client.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from src.conf.config import settings
from src.workers.exceptions import ExternalServiceError, PermanentError, RetryableError
from src.workers.sync_utils import run_sync


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(RetryableError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 5},
    name="src.workers.tasks.crm.create_crm_order",
    soft_time_limit=25,
    time_limit=30,
)
def create_crm_order(
    self,
    order_data: dict[str, Any],
) -> dict:
    """Create an order in Snitkix CRM.

    This task handles order creation with automatic retries
    for transient failures (network issues, rate limits).

    Args:
        order_data: Order data dictionary containing:
            - external_id: Unique order identifier
            - customer: Customer info (name, phone, city, nova_poshta)
            - items: List of order items
            - source: Order source (telegram, manychat)
            - source_id: User ID from source

    Returns:
        dict with order creation result
    """
    from src.integrations.crm.snitkix import get_snitkix_client
    from src.services.order_model import CustomerInfo, Order, OrderItem

    external_id = order_data.get("external_id", "unknown")

    logger.info(
        "[WORKER:CRM] Creating order external_id=%s attempt=%d",
        external_id,
        self.request.retries + 1,
    )

    if not settings.snitkix_enabled:
        logger.warning("[WORKER:CRM] Snitkix CRM not configured")
        return {
            "status": "skipped",
            "reason": "crm_not_configured",
        }

    # Validate input
    if not order_data.get("customer"):
        raise PermanentError("Missing customer data", error_code="INVALID_INPUT")

    if not order_data.get("items"):
        raise PermanentError("Missing order items", error_code="INVALID_INPUT")

    try:
        # Build Order model from dict
        customer_data = order_data.get("customer", {})
        customer = CustomerInfo(
            full_name=customer_data.get("full_name"),
            phone=customer_data.get("phone"),
            city=customer_data.get("city"),
            nova_poshta_branch=customer_data.get("nova_poshta_branch"),
            telegram_id=customer_data.get("telegram_id"),
            manychat_id=customer_data.get("manychat_id"),
        )

        items = []
        for item_data in order_data.get("items", []):
            items.append(
                OrderItem(
                    product_id=item_data.get("product_id", 0),
                    product_name=item_data.get("product_name", ""),
                    size=item_data.get("size", ""),
                    color=item_data.get("color", ""),
                    price=item_data.get("price", 0.0),
                )
            )

        order = Order(
            external_id=external_id,
            customer=customer,
            items=items,
            source=order_data.get("source", "unknown"),
            source_id=order_data.get("source_id", ""),
        )

        # Send to CRM using sync wrapper (NO asyncio.run!)
        async def _create_order():
            crm = get_snitkix_client()
            return await crm.create_order(order)

        response = run_sync(_create_order())

        if response.success:
            logger.info(
                "[WORKER:CRM] Order created successfully: %s",
                response.order_id,
            )
            return {
                "status": "created",
                "order_id": response.order_id,
                "external_id": order.external_id,
            }
        else:
            logger.error(
                "[WORKER:CRM] Order creation failed: %s",
                response.error,
            )
            # Business logic error - don't retry
            raise PermanentError(f"CRM rejected order: {response.error}", error_code="CRM_REJECTED")

    except PermanentError:
        raise  # Don't retry
    except Exception as e:
        logger.exception(
            "[WORKER:CRM] Error creating order %s: %s",
            external_id,
            e,
        )
        # Wrap in RetryableError for automatic retry
        raise ExternalServiceError("snitkix_crm", str(e)) from e


@shared_task(
    bind=True,
    name="src.workers.tasks.crm.sync_order_status",
)
def sync_order_status(
    self,
    order_id: str,
    session_id: str,
) -> dict:
    """Sync order status from CRM back to session.

    This can be used to update conversation state
    when order status changes in CRM.

    Args:
        order_id: CRM order ID
        session_id: Session ID to update

    Returns:
        dict with sync result
    """
    logger.info(
        "[WORKER:CRM] Syncing order status order_id=%s session=%s",
        order_id,
        session_id,
    )

    # TODO: Implement when CRM status webhook is available
    return {
        "status": "not_implemented",
        "order_id": order_id,
    }
