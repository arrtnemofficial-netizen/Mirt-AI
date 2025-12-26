"""CRM background tasks.

These tasks handle:
- Creating orders in Snitkix CRM
- Retrying failed order submissions
- Syncing order status

Uses sync_utils to properly call async CRM client.
"""

from __future__ import annotations

import logging
from datetime import datetime
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

            # Update CRM order status in PostgreSQL
            try:
                # Update crm_orders in PostgreSQL
                import psycopg
                from src.services.postgres_pool import get_postgres_url
                
                postgres_url = get_postgres_url()
                with psycopg.connect(postgres_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE crm_orders
                            SET status = 'created',
                                crm_order_id = %s,
                                error_message = NULL,
                                updated_at = NOW()
                            WHERE external_id = %s
                            """,
                            (response.order_id, external_id),
                        )
                        conn.commit()

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

            # Update CRM order with failed status in PostgreSQL
            try:
                import psycopg
                from src.services.postgres_pool import get_postgres_url
                
                postgres_url = get_postgres_url()
                with psycopg.connect(postgres_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE crm_orders
                            SET status = 'failed',
                                error_message = %s,
                                updated_at = NOW()
                            WHERE external_id = %s
                            """,
                            (f"CRM rejected order: {response.error}", external_id),
                        )
                        conn.commit()

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

        # Update session state in PostgreSQL
        import psycopg
        from src.services.postgres_pool import get_postgres_url
        
        postgres_url = get_postgres_url()
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_sessions
                    SET order_status = %s,
                        order_id = %s,
                        updated_at = NOW()
                    WHERE session_id = %s
                    """,
                    (new_status, order_id, session_id),
                )
                conn.commit()

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
    logger.info("[WORKER:CRM] Checking pending orders for status updates")

    if not settings.snitkix_enabled:
        return {"status": "skipped", "reason": "crm_not_configured"}

    # Use PostgreSQL
    try:
        import psycopg
        from psycopg.rows import dict_row
        from src.services.postgres_pool import get_postgres_url
        
        # Get sessions with pending orders from PostgreSQL
        postgres_url = get_postgres_url()
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT session_id, order_id, order_status
                    FROM agent_sessions
                    WHERE order_id IS NOT NULL
                    AND order_status IN ('pending', 'processing', 'new')
                    """
                )
                rows = cur.fetchall()

        if not rows:
            return {"status": "ok", "checked": 0}

        queued = 0
        for row in rows:
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
