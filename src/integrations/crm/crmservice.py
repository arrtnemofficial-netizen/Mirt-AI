"""CRM Service Layer.

High-level service for managing CRM orders with persistence,
idempotency checks, and bidirectional status synchronization.

This service provides:
- Order creation with duplicate prevention
- Order status updates and retrieval
- Session ↔ CRM order mapping persistence
- Error handling and retry logic
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore

from src.conf.config import settings
from src.services.postgres_pool import get_postgres_url


logger = logging.getLogger(__name__)


class CRMService:
    """High-level CRM service with persistence and error handling."""

    def __init__(self):
        pass

    async def create_order_with_persistence(
        self,
        session_id: str,
        order_data: dict[str, Any],
        external_id: str | None = None,
    ) -> dict[str, Any]:
        """Create order in CRM with persistence and idempotency.

        Args:
            session_id: Chat session identifier
            order_data: Order data dict (customer, items, source, etc.)
            external_id: Unique order ID (generated if not provided)

        Returns:
            dict with creation result and CRM order ID
        """
        if not settings.snitkix_enabled:
            logger.warning("[CRM:SERVICE] Snitkix CRM not configured")
            return {"status": "skipped", "reason": "crm_not_configured"}

        # Generate external_id if not provided
        # WARNING: This fallback is non-deterministic! Prefer passing deterministic external_id
        if not external_id:
            import hashlib

            # Use session_id + current day as fallback (still not ideal, but better than timestamp)
            day_key = datetime.now(UTC).strftime("%Y-%m-%d")
            fallback_hash = hashlib.sha256(f"{session_id}|{day_key}".encode()).hexdigest()[:16]
            external_id = f"{session_id}_{fallback_hash}"
            logger.warning(
                "[CRM:SERVICE] Using non-deterministic fallback external_id=%s. "
                "Pass explicit external_id for idempotency!",
                external_id,
            )

        # Check for existing order to prevent duplicates
        existing = await self._get_existing_order(external_id)
        if existing:
            logger.info(
                "[CRM:SERVICE] Order already exists external_id=%s crm_order_id=%s",
                external_id,
                existing["crm_order_id"],
            )
            return {
                "status": "exists",
                "external_id": external_id,
                "crm_order_id": existing["crm_order_id"],
                "session_id": session_id,
            }

        try:
            # Store pending order in database first
            await self._store_order_mapping(
                session_id=session_id,
                external_id=external_id,
                crm_order_id=None,
                status="pending",
                order_data=order_data,
            )

            # Create order directly in CRM (no Celery)
            from src.integrations.crm.snitkix import get_snitkix_client
            from src.services.order_model import CustomerInfo, Order, OrderItem

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

            crm = get_snitkix_client()
            response = await crm.create_order(order)

            if response.success:
                # Update order mapping with CRM order ID
                await self._update_order_mapping(
                    external_id=external_id,
                    crm_order_id=response.order_id,
                    status="created",
                )
                logger.info(
                    "[CRM:SERVICE] Order created successfully external_id=%s crm_order_id=%s",
                    external_id,
                    response.order_id,
                )
                return {
                    "status": "created",
                    "external_id": external_id,
                    "crm_order_id": response.order_id,
                    "session_id": session_id,
                }
            else:
                # Update stored order with error status
                await self._update_order_status(
                    external_id=external_id, status="failed", error_message=response.error
                )
                logger.error(
                    "[CRM:SERVICE] Order creation failed external_id=%s error=%s",
                    external_id,
                    response.error,
                )
                return {
                    "status": "failed",
                    "external_id": external_id,
                    "error": response.error,
                    "session_id": session_id,
                }

        except Exception as e:
            logger.exception(
                "[CRM:SERVICE] Failed to queue order creation external_id=%s: %s",
                external_id,
                e,
            )
            # Update stored order with error status
            await self._update_order_status(external_id, "failed", str(e))
            return {
                "status": "failed",
                "external_id": external_id,
                "error": str(e),
                "session_id": session_id,
            }

    async def update_order_from_crm(
        self,
        external_id: str,
        crm_order_id: str,
        status: str = "created",
    ) -> bool:
        """Update stored order with CRM order ID and status.

        Called after successful CRM creation.
        """
        try:
            await self._update_order_mapping(
                external_id=external_id,
                crm_order_id=crm_order_id,
                status=status,
            )
            logger.info(
                "[CRM:SERVICE] Updated order mapping external_id=%s crm_order_id=%s status=%s",
                external_id,
                crm_order_id,
                status,
            )
            return True
        except Exception as e:
            logger.exception(
                "[CRM:SERVICE] Failed to update order mapping external_id=%s: %s",
                external_id,
                e,
            )
            return False

    async def handle_webhook_status_update(
        self,
        crm_order_id: str,
        new_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handle status update from CRM webhook.

        Updates local storage and triggers session sync if needed.
        """
        try:
            # Find order by CRM order ID
            order_record = await self._get_order_by_crm_id(crm_order_id)
            if not order_record:
                logger.warning(
                    "[CRM:SERVICE] Received webhook for unknown CRM order %s",
                    crm_order_id,
                )
                return {"status": "not_found", "crm_order_id": crm_order_id}

            old_status = order_record["status"]
            if old_status == new_status:
                logger.info(
                    "[CRM:SERVICE] Status unchanged for CRM order %s: %s",
                    crm_order_id,
                    new_status,
                )
                return {"status": "unchanged", "crm_order_id": crm_order_id}

            # Update status in database
            await self._update_order_status(order_record["external_id"], new_status, metadata)

            # Sync order status to session (no Celery)
            await self._sync_order_status(
                crm_order_id,
                order_record["session_id"],
                new_status,
            )

            logger.info(
                "[CRM:SERVICE] Status updated CRM order %s: %s → %s",
                crm_order_id,
                old_status,
                new_status,
            )

            return {
                "status": "updated",
                "crm_order_id": crm_order_id,
                "old_status": old_status,
                "new_status": new_status,
                "session_id": order_record["session_id"],
            }

        except Exception as e:
            logger.exception(
                "[CRM:SERVICE] Failed to handle webhook for CRM order %s: %s",
                crm_order_id,
                e,
            )
            return {
                "status": "error",
                "crm_order_id": crm_order_id,
                "error": str(e),
            }

    async def get_order_status(
        self,
        session_id: str | None = None,
        external_id: str | None = None,
        crm_order_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Get order status by any identifier."""
        try:
            if external_id:
                return await self._get_existing_order(external_id)
            elif crm_order_id:
                return await self._get_order_by_crm_id(crm_order_id)
            elif session_id:
                return await self._get_latest_order_by_session(session_id)
            else:
                return None
        except Exception as e:
            logger.exception("[CRM:SERVICE] Failed to get order status: %s", e)
            return None

    async def get_session_orders(self, session_id: str) -> list[dict[str, Any]]:
        """Get all orders for a session."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return []

        try:
            try:
                url = get_postgres_url()
            except ValueError:
                return []
            
            def _get_session_orders_sync():
                with psycopg.connect(url) as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            SELECT * FROM crm_orders
                            WHERE session_id = %s
                            ORDER BY created_at DESC
                            """,
                            (session_id,),
                        )
                        rows = cur.fetchall()
                        return [dict(row) for row in rows]
            
            return await asyncio.to_thread(_get_session_orders_sync)
        except Exception as e:
            logger.exception(
                "[CRM:SERVICE] Failed to get orders for session %s: %s",
                session_id,
                e,
            )
            return []

    # Private persistence methods

    async def _store_order_mapping(
        self,
        session_id: str,
        external_id: str,
        crm_order_id: str | None,
        status: str,
        order_data: dict[str, Any],
    ) -> None:
        """Store order mapping in PostgreSQL."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return

        try:
            url = get_postgres_url()
        except ValueError:
            return
        
        def _store_order_mapping_sync():
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO crm_orders (
                            session_id, external_id, crm_order_id, status, order_data
                        )
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            session_id,
                            external_id,
                            crm_order_id,
                            status,
                            json.dumps(order_data),
                        ),
                    )
                    conn.commit()
        
        await asyncio.to_thread(_store_order_mapping_sync)

    async def _update_order_mapping(
        self,
        external_id: str,
        crm_order_id: str,
        status: str,
    ) -> None:
        """Update order mapping with CRM order ID and status."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return

        try:
            url = get_postgres_url()
        except ValueError:
            return
        
        def _update_order_mapping_sync():
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE crm_orders
                        SET crm_order_id = %s, status = %s, updated_at = NOW()
                        WHERE external_id = %s
                        """,
                        (crm_order_id, status, external_id),
                    )
                    conn.commit()
        
        await asyncio.to_thread(_update_order_mapping_sync)

    async def _update_order_status(
        self,
        external_id: str,
        status: str,
        task_id: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update order status with optional task_id and error_message."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return

        try:
            url = get_postgres_url()
        except ValueError:
            return
        
        def _update_order_status_sync():
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    # Build UPDATE query dynamically
                    updates = ["status = %s", "updated_at = NOW()"]
                    params = [status]
                    
                    if task_id:
                        updates.append("task_id = %s")
                        params.append(task_id)
                    if error_message:
                        updates.append("error_message = %s")
                        params.append(error_message)
                    if metadata:
                        updates.append("metadata = %s::jsonb")
                        params.append(json.dumps(metadata))
                    
                    params.append(external_id)
                    query = f"""
                        UPDATE crm_orders
                        SET {', '.join(updates)}
                        WHERE external_id = %s
                    """
                    cur.execute(query, params)
                    conn.commit()
        
        await asyncio.to_thread(_update_order_status_sync)

    async def _get_existing_order(self, external_id: str) -> dict[str, Any] | None:
        """Get existing order by external ID."""
        if psycopg is None:
            return None

        try:
            try:
                url = get_postgres_url()
            except ValueError:
                return None
            
            def _get_existing_order_sync():
                with psycopg.connect(url) as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            SELECT * FROM crm_orders
                            WHERE external_id = %s
                            LIMIT 1
                            """,
                            (external_id,),
                        )
                        row = cur.fetchone()
                        return dict(row) if row else None
            
            return await asyncio.to_thread(_get_existing_order_sync)
        except Exception:
            return None

    async def _get_order_by_crm_id(self, crm_order_id: str) -> dict[str, Any] | None:
        """Get order by CRM order ID."""
        if psycopg is None:
            return None

        try:
            try:
                url = get_postgres_url()
            except ValueError:
                return None
            
            def _get_order_by_crm_id_sync():
                with psycopg.connect(url) as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            SELECT * FROM crm_orders
                            WHERE crm_order_id = %s
                            LIMIT 1
                            """,
                            (crm_order_id,),
                        )
                        row = cur.fetchone()
                        return dict(row) if row else None
            
            return await asyncio.to_thread(_get_order_by_crm_id_sync)
        except Exception:
            return None

    async def _get_latest_order_by_session(self, session_id: str) -> dict[str, Any] | None:
        """Get latest order for session."""
        if psycopg is None:
            return None

        try:
            try:
                url = get_postgres_url()
            except ValueError:
                return None
            
            def _get_latest_order_by_session_sync():
                with psycopg.connect(url) as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            SELECT * FROM crm_orders
                            WHERE session_id = %s
                            ORDER BY created_at DESC
                            LIMIT 1
                            """,
                            (session_id,),
                        )
                        row = cur.fetchone()
                        return dict(row) if row else None
            
            return await asyncio.to_thread(_get_latest_order_by_session_sync)
        except Exception:
            return None

    async def _sync_order_status(
        self,
        order_id: str,
        session_id: str,
        new_status: str | None = None,
    ) -> None:
        """Sync order status from CRM back to session.

        Updates session state in PostgreSQL with order status.
        This replaces the Celery task sync_order_status.

        Args:
            order_id: CRM order ID
            session_id: Session ID to update
            new_status: New order status (if known from webhook)
        """
        try:
            # If status not provided, fetch from CRM
            if not new_status:
                from src.integrations.crm.snitkix import get_snitkix_client

                crm = get_snitkix_client()
                order_status = await crm.get_order_status(order_id)
                new_status = order_status.status if order_status else None

            if not new_status:
                logger.warning(
                    "[CRM:SERVICE] Could not fetch status for order %s", order_id
                )
                return

            # Update session state in PostgreSQL
            if psycopg:
                try:
                    url = get_postgres_url()
                except ValueError:
                    return
                
                def _sync_order_status_sync():
                    with psycopg.connect(url) as conn:
                        with conn.cursor() as cur:
                            # Update state JSONB field
                            cur.execute(
                                """
                                UPDATE agent_sessions
                                SET state = jsonb_set(
                                    jsonb_set(state, '{order_status}', %s::jsonb),
                                    '{order_id}', %s::jsonb
                                ),
                                updated_at = NOW()
                                WHERE session_id = %s
                                """,
                                (json.dumps(new_status), json.dumps(order_id), session_id),
                            )
                            conn.commit()
                
                await asyncio.to_thread(_sync_order_status_sync)

                logger.info(
                    "[CRM:SERVICE] Updated session %s with order status: %s",
                    session_id,
                    new_status,
                )

        except Exception as e:
            logger.exception(
                "[CRM:SERVICE] Error syncing order status %s: %s",
                order_id,
                e,
            )


# Global service instance
_crm_service: CRMService | None = None


def get_crm_service() -> CRMService:
    """Get global CRM service instance."""
    global _crm_service
    if _crm_service is None:
        _crm_service = CRMService()
    return _crm_service
