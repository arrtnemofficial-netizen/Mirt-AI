"""
Order Service - Supabase implementation.
========================================
Handles order creation and history retrieval.
"""

from __future__ import annotations

import logging
from typing import Any

from src.services.supabase_client import get_supabase_client


logger = logging.getLogger(__name__)


class OrderService:
    """
    Order management service backed by Supabase.
    """

    def __init__(self) -> None:
        self.client = get_supabase_client()

    async def create_order(self, order_data: dict[str, Any]) -> str | None:
        """
        Create a new order in the database.

        Args:
            order_data: Dict containing order details (from Order model)

        Returns:
            Created order ID (str) or None if failed
        """
        if not self.client:
            logger.warning("Supabase client not available, cannot save order")
            return None

        try:
            # 1. Prepare Order Payload
            customer = order_data.get("customer", {})
            totals = order_data.get("totals", {})

            order_payload = {
                "user_id": order_data.get("source_id") or "unknown",
                "session_id": order_data.get("external_id"),
                # Support both "full_name" (from payment.py) and "name" (legacy)
                "customer_name": customer.get("full_name") or customer.get("name"),
                "customer_phone": customer.get("phone"),
                "customer_city": customer.get("city"),
                "delivery_method": order_data.get("delivery_method"),
                # Support both "nova_poshta_branch" and "delivery_address"
                "delivery_address": customer.get("nova_poshta_branch") or customer.get("delivery_address"),
                "status": order_data.get("status", "new"),
                "total_amount": totals.get("total", 0),
                "notes": order_data.get("notes"),
                # User nickname from Telegram/Instagram
                "user_nickname": order_data.get("user_nickname") or customer.get("username"),
            }

            # 2. Insert Order
            response = self.client.table("orders").insert(order_payload).execute()

            if not response.data:
                logger.error("Failed to insert order, no data returned")
                return None

            new_order = response.data[0]
            order_id = new_order["id"]

            # 3. Insert Order Items
            items = order_data.get("items", [])
            if items:
                items_payload = []
                for item in items:
                    items_payload.append(
                        {
                            "order_id": order_id,
                            "product_id": item.get("product_id"),
                            "product_name": item.get("name"),
                            "quantity": item.get("quantity", 1),
                            "price_at_purchase": item.get("price", 0),
                            "selected_size": item.get("size"),
                            "selected_color": item.get("color"),
                        }
                    )

                self.client.table("order_items").insert(items_payload).execute()

            logger.info("Order created successfully: ID %s", order_id)
            return str(order_id)

        except Exception as e:
            logger.error("Create order failed: %s", e)
            return None

    async def get_user_orders(self, user_id: str) -> list[dict[str, Any]]:
        """Get order history for a user."""
        if not self.client:
            return []

        try:
            # Fetch orders with items
            response = (
                self.client.table("orders")
                .select("*, order_items(*)")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .execute()
            )
            return response.data or []
        except Exception as e:
            logger.error("Get user orders failed: %s", e)
            return []

    async def get_order_by_id(self, order_id: str) -> dict[str, Any] | None:
        """Get full order details by ID."""
        if not self.client:
            return None

        try:
            response = (
                self.client.table("orders")
                .select("*, order_items(*)")
                .eq("id", order_id)
                .single()
                .execute()
            )
            return response.data
        except Exception as e:
            logger.error("Get order failed: %s", e)
            return None
