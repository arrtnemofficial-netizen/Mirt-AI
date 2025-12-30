# helpers/payment/utils.py
"""
Payment utilities - price hydration and common helpers.
"""

from __future__ import annotations

import logging
from typing import Any

from src.services.catalog import CatalogService

logger = logging.getLogger(__name__)


async def ensure_prices_from_catalog(
    products: list[dict[str, Any]],
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    """Ensure all products have valid prices from catalog."""
    if not products:
        return products

    catalog = CatalogService()
    cache: dict[str, dict[str, Any]] = {}
    updated: list[dict[str, Any]] = []

    for p in products:
        try:
            price = p.get("price", 0)
            if isinstance(price, (int, float)) and price > 0:
                updated.append(p)
                continue

            name = str(p.get("name") or "").strip()
            size = p.get("size")
            if not name:
                updated.append(p)
                continue

            if name in cache:
                db_product = cache[name]
            else:
                results = await catalog.search_products(query=name, limit=1)
                db_product = results[0] if results else {}
                cache[name] = db_product

            if db_product:
                db_price = CatalogService.get_price_for_size(db_product, size)
                if db_price and db_price > 0:
                    p = {**p, "price": db_price}
        except Exception as e:
            logger.debug("[SESSION %s] Price hydration skipped: %s", session_id, str(e)[:120])

        updated.append(p)

    return updated


# Template for thank you message (kept here for centralization)
PAYMENT_TEMPLATES = {
    "THANK_YOU": """Дякуємо за замовлення🥰

Гарного вам дня та мирного неба 🕊""",
}
