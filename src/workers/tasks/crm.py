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
    from src.services.data.order_model import CustomerInfo, Order, OrderItem

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
<<<<<<< Updated upstream
=======

            # Update CRM order status in database
            try:
                from src.services.infra.supabase_client import get_supabase_client

                supabase = get_supabase_client()

                supabase.table("crm_orders").update(
                    {
                        "status": "created",
                        "crm_order_id": response.order_id,
                        "error_message": None,
                        "updated_at": datetime.now().isoformat(),
                    }
                ).eq("external_id", external_id).execute()

                logger.info(
                    "[WORKER:CRM] Updated crm_orders status to 'created' for external_id=%s",
                    external_id,
                )
            except Exception as e:
                logger.error(
                    "[WORKER:CRM] Failed to update crm_orders status for external_id=%s: %s",
                    external_id,
                    e,
                )

>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
=======

            # Update CRM order with failed status
            try:
                from src.services.infra.supabase_client import get_supabase_client

                supabase = get_supabase_client()

                supabase.table("crm_orders").update(
                    {
                        "status": "failed",
                        "error_message": f"CRM rejected order: {response.error}",
                        "updated_at": datetime.now().isoformat(),
                    }
                ).eq("external_id", external_id).execute()

                logger.info(
                    "[WORKER:CRM] Updated crm_orders status to 'failed' for external_id=%s",
                    external_id,
                )
            except Exception as e:
                logger.error(
                    "[WORKER:CRM] Failed to update crm_orders failed status for external_id=%s: %s",
                    external_id,
                    e,
                )

>>>>>>> Stashed changes
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
    autoretry_for=(RetryableError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.crm.sync_order_status",
    soft_time_limit=25,
    time_limit=30,
)
def sync_order_status(
    self,
    order_id: str,
    session_id: str,
    new_status: str | None = None,
) -> dict:
    """Sync order status from CRM back to session.

    This task updates conversation state when order status changes in CRM.
    Can be triggered by CRM webhooks or polled periodically.

    Args:
        order_id: CRM order ID
        session_id: Session ID to update
        new_status: New order status (if known from webhook)

    Returns:
        dict with sync result
    """
    from src.integrations.crm.snitkix import get_snitkix_client
    from src.services.infra.supabase_client import get_supabase_client

    logger.info(
        "[WORKER:CRM] Syncing order status order_id=%s session=%s new_status=%s",
        order_id,
        session_id,
        new_status,
    )

    if not settings.snitkix_enabled:
        logger.warning("[WORKER:CRM] Snitkix CRM not configured")
        return {"status": "skipped", "reason": "crm_not_configured"}

    try:
        # If status not provided, fetch from CRM
        if not new_status:

            async def _get_status():
                crm = get_snitkix_client()
                return await crm.get_order_status(order_id)

            order_status = run_sync(_get_status())
            new_status = order_status.status if order_status else None

        if not new_status:
            logger.warning("[WORKER:CRM] Could not fetch status for order %s", order_id)
            return {"status": "error", "reason": "status_not_found"}

        # Update session state in Supabase
        client = get_supabase_client()
        if client:
            # Update agent_sessions with order status
            client.table("agent_sessions").update(
                {
                    "order_status": new_status,
                    "order_id": order_id,
                }
            ).eq("session_id", session_id).execute()

            logger.info(
                "[WORKER:CRM] Updated session %s with order status: %s",
                session_id,
                new_status,
            )

        return {
            "status": "synced",
            "order_id": order_id,
            "order_status": new_status,
            "session_id": session_id,
        }

    except Exception as e:
        logger.exception(
            "[WORKER:CRM] Error syncing order status %s: %s",
            order_id,
            e,
        )
        raise ExternalServiceError("snitkix_crm", str(e)) from e


@shared_task(
    bind=True,
    name="src.workers.tasks.crm.check_pending_orders",
)
def check_pending_orders(self) -> dict:
    """Check all pending orders for status updates.

    Periodic task to sync order statuses from CRM.
    Runs via Celery Beat.

    Returns:
        dict with check results
    """
    from src.services.infra.supabase_client import get_supabase_client

    logger.info("[WORKER:CRM] Checking pending orders for status updates")

    if not settings.snitkix_enabled:
        return {"status": "skipped", "reason": "crm_not_configured"}

    client = get_supabase_client()
    if not client:
        return {"status": "skipped", "reason": "no_supabase"}

    try:
        # Get sessions with pending orders
        response = (
            client.table("agent_sessions")
            .select("session_id, order_id, order_status")
            .not_.is_("order_id", "null")
            .in_("order_status", ["pending", "processing", "new"])
            .execute()
        )

        if not response.data:
            return {"status": "ok", "checked": 0}

        queued = 0
        for row in response.data:
            # Queue status sync for each pending order
            sync_order_status.delay(
                order_id=row["order_id"],
                session_id=row["session_id"],
            )
            queued += 1

        logger.info("[WORKER:CRM] Queued %d order status checks", queued)
        return {"status": "ok", "queued": queued}

    except Exception as e:
        logger.exception("[WORKER:CRM] Error checking pending orders: %s", e)
        return {"status": "error", "error": str(e)}
