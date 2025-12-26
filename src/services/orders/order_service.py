"""
Order Service - PostgreSQL implementation.
==========================================
Handles order creation and history retrieval.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore

from src.services.storage import get_postgres_url
from src.services.common import ServiceUnavailableError


logger = logging.getLogger(__name__)


class OrderService:
    """
    Order management service backed by PostgreSQL.
    """

    def __init__(self) -> None:
        pass

    async def create_order(self, order_data: dict[str, Any]) -> str | None:
        """
        Create a new order in the database.

        Args:
            order_data: Dict containing order details (from Order model)

        Returns:
            Created order ID (str) or None if failed
        """
        if psycopg is None:
            logger.error(
                "[ORDER] CRITICAL: psycopg not installed - order will NOT be saved!"
            )
            raise ServiceUnavailableError("database", "Cannot save order - psycopg not installed")

        try:
            # 1. Prepare Order Payload
            customer = order_data.get("customer", {})
            totals = order_data.get("totals", {})

            user_id = order_data.get("source_id") or "unknown"
            session_id = order_data.get("external_id")
            customer_name = customer.get("full_name") or customer.get("name")
            customer_phone = customer.get("phone")
            customer_city = customer.get("city")
            delivery_method = order_data.get("delivery_method")
            delivery_address = customer.get("nova_poshta_branch") or customer.get("delivery_address")
            status = order_data.get("status", "new")
            total_amount = totals.get("total", 0)
            notes = order_data.get("notes")
            user_nickname = order_data.get("user_nickname") or customer.get("username")

            url = get_postgres_url()
            
            # 2. Upsert Order (handles duplicates atomically) - wrap sync call in thread
            def _create_order_sync():
                with psycopg.connect(url) as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        # Upsert order
                        cur.execute(
                            """
                            INSERT INTO orders (
                                user_id, session_id, customer_name, customer_phone,
                                customer_city, delivery_method, delivery_address,
                                status, total_amount, notes, user_nickname
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (session_id) 
                            DO UPDATE SET
                                user_id = EXCLUDED.user_id,
                                customer_name = EXCLUDED.customer_name,
                                customer_phone = EXCLUDED.customer_phone,
                                customer_city = EXCLUDED.customer_city,
                                delivery_method = EXCLUDED.delivery_method,
                                delivery_address = EXCLUDED.delivery_address,
                                status = EXCLUDED.status,
                                total_amount = EXCLUDED.total_amount,
                                notes = EXCLUDED.notes,
                                user_nickname = EXCLUDED.user_nickname,
                                updated_at = NOW()
                            RETURNING id, created_at, updated_at
                            """,
                            (
                                user_id, session_id, customer_name, customer_phone,
                                customer_city, delivery_method, delivery_address,
                                status, total_amount, notes, user_nickname
                            ),
                        )
                        
                        new_order = cur.fetchone()
                        if not new_order:
                            logger.error("Failed to upsert order, no data returned")
                            return None
                        
                        order_id = new_order["id"]
                        created_at = new_order["created_at"]
                        updated_at = new_order["updated_at"]
                        
                        # 3. Insert Order Items (only if this is a new order)
                        # Check if order was just created or updated
                        if created_at == updated_at:
                            items = order_data.get("items", [])
                            if items:
                                for item in items:
                                    cur.execute(
                                        """
                                        INSERT INTO order_items (
                                            order_id, product_id, product_name,
                                            quantity, price_at_purchase,
                                            selected_size, selected_color
                                        )
                                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                                        """,
                                        (
                                            order_id,
                                            item.get("product_id"),
                                            item.get("name"),
                                            item.get("quantity", 1),
                                            item.get("price", 0),
                                            item.get("size"),
                                            item.get("color"),
                                        ),
                                    )
                        
                        conn.commit()
                        logger.info("Order upserted successfully: ID %s", order_id)
                        return str(order_id)
            
            return await asyncio.to_thread(_create_order_sync)

        except Exception as e:
            logger.error("Create order failed: %s", e)
            return None

    async def get_user_orders(self, user_id: str) -> list[dict[str, Any]]:
        """Get order history for a user."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return []

        try:
            url = get_postgres_url()
            
            def _get_user_orders_sync():
                with psycopg.connect(url) as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        # Fetch orders
                        cur.execute(
                            """
                            SELECT * FROM orders
                            WHERE user_id = %s
                            ORDER BY created_at DESC
                            """,
                            (user_id,),
                        )
                        orders = cur.fetchall()
                        
                        # Fetch order items for each order
                        result = []
                        for order in orders:
                            order_dict = dict(order)
                            cur.execute(
                                """
                                SELECT * FROM order_items
                                WHERE order_id = %s
                                ORDER BY id
                                """,
                                (order_dict["id"],),
                            )
                            items = cur.fetchall()
                            order_dict["order_items"] = [dict(item) for item in items]
                            result.append(order_dict)
                        
                        return result
            
            return await asyncio.to_thread(_get_user_orders_sync)
        except Exception as e:
            logger.error("Get user orders failed: %s", e)
            return []

    async def get_order_by_id(self, order_id: str) -> dict[str, Any] | None:
        """Get full order details by ID."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return None

        try:
            url = get_postgres_url()
            
            def _get_order_by_id_sync():
                with psycopg.connect(url) as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        # Fetch order
                        cur.execute(
                            """
                            SELECT * FROM orders
                            WHERE id = %s
                            """,
                            (order_id,),
                        )
                        order = cur.fetchone()
                        
                        if not order:
                            return None
                        
                        order_dict = dict(order)
                        
                        # Fetch order items
                        cur.execute(
                            """
                            SELECT * FROM order_items
                            WHERE order_id = %s
                            ORDER BY id
                            """,
                            (order_id,),
                        )
                        items = cur.fetchall()
                        order_dict["order_items"] = [dict(item) for item in items]
                        
                        return order_dict
            
            return await asyncio.to_thread(_get_order_by_id_sync)
        except Exception as e:
            logger.error("Get order failed: %s", e)
            return None
