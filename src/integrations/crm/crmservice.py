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

import logging
from datetime import UTC, datetime
from typing import Any

from src.conf.config import settings
from src.services.supabase_client import get_supabase_client
from src.workers.tasks.crm import create_crm_order, sync_order_status


logger = logging.getLogger(__name__)


class CRMService:
    """High-level CRM service with persistence and error handling."""

    def __init__(self):
        self.supabase = get_supabase_client()

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
            day_key = datetime.now(UTC).strftime('%Y-%m-%d')
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

            # Trigger CRM order creation via Celery
            task_result = create_crm_order.delay(
                {
                    "external_id": external_id,
                    **order_data,
                }
            )

            logger.info(
                "[CRM:SERVICE] Order creation task queued external_id=%s task_id=%s",
                external_id,
                task_result.id,
            )

            return {
                "status": "queued",
                "external_id": external_id,
                "task_id": task_result.id,
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
        
        Called by Celery task after successful CRM creation.
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
            await self._update_order_status(
                order_record["external_id"], new_status, metadata
            )

            # Trigger session sync to notify user
            sync_order_status.delay(
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
        try:
            response = (
                self.supabase.table("crm_orders")
                .select("*")
                .eq("session_id", session_id)
                .order("created_at", desc=True)
                .execute()
            )
            return response.data or []
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
        """Store order mapping in Supabase."""
        self.supabase.table("crm_orders").insert({
            "session_id": session_id,
            "external_id": external_id,
            "crm_order_id": crm_order_id,
            "status": status,
            "order_data": order_data,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }).execute()

    async def _update_order_mapping(
        self,
        external_id: str,
        crm_order_id: str,
        status: str,
    ) -> None:
        """Update order mapping with CRM order ID and status."""
        self.supabase.table("crm_orders").update({
            "crm_order_id": crm_order_id,
            "status": status,
            "updated_at": datetime.now(UTC).isoformat(),
        }).eq("external_id", external_id).execute()

    async def _update_order_status(
        self,
        external_id: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update order status."""
        update_data = {
            "status": status,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        if metadata:
            update_data["metadata"] = metadata

        self.supabase.table("crm_orders").update(update_data).eq(
            "external_id", external_id
        ).execute()

    async def _get_existing_order(self, external_id: str) -> dict[str, Any] | None:
        """Get existing order by external ID."""
        try:
            response = (
                self.supabase.table("crm_orders")
                .select("*")
                .eq("external_id", external_id)
                .single()
                .execute()
            )
            return response.data
        except Exception:
            return None

    async def _get_order_by_crm_id(self, crm_order_id: str) -> dict[str, Any] | None:
        """Get order by CRM order ID."""
        try:
            response = (
                self.supabase.table("crm_orders")
                .select("*")
                .eq("crm_order_id", crm_order_id)
                .single()
                .execute()
            )
            return response.data
        except Exception:
            return None

    async def _get_latest_order_by_session(self, session_id: str) -> dict[str, Any] | None:
        """Get latest order for session."""
        try:
            response = (
                self.supabase.table("crm_orders")
                .select("*")
                .eq("session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .single()
                .execute()
            )
            return response.data
        except Exception:
            return None


# Global service instance
_crm_service: CRMService | None = None


def get_crm_service() -> CRMService:
    """Get global CRM service instance."""
    global _crm_service
    if _crm_service is None:
        _crm_service = CRMService()
    return _crm_service
