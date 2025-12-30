"""
Order Service - PostgreSQL implementation.
==========================================
Handles order creation and history retrieval.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any


try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore

from src.services.common import ServiceUnavailableError
from src.services.storage import get_postgres_url


logger = logging.getLogger(__name__)


class OrderService:
    """
    Order management service backed by PostgreSQL.
    """

    def __init__(self) -> None:
        pass

    async def create_order(self, order_data: dict[str, Any]) -> str | None:
        # [USER-OVERRIDE] Disabled local order persistence
        # "НЕТ Я ЖЕ ОТКОЗАЛСЯ ОТ ОРДЕРС!!"
        logger.info("OrderService.create_order: MOCK SKIPPED (tables deleted)")
        return "mock_skipped_id"  # Return a mock ID so callers don't crash

    async def get_user_orders(self, user_id: str) -> list[dict[str, Any]]:
        """Get order history for a user."""
        # [USER-OVERRIDE] Disabled local order persistence
        # "НЕТ Я ЖЕ ОТКОЗАЛСЯ ОТ ОРДЕРС!!"
        return []

    async def get_order_by_id(self, order_id: str) -> dict[str, Any] | None:
        """Get full order details by ID."""
        # [USER-OVERRIDE] Disabled local order persistence
        return None
