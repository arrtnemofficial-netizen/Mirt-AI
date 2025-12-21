"""
Vision Node - Product Enrichment.
=================================
Handles looking up products in the database and enriching vision results with real catalog data.
"""
from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from src.services.data.catalog_service import CatalogService

logger = logging.getLogger(__name__)


async def enrich_product_from_db(
    product_name: str, color: str | None = None
) -> dict[str, Any] | None:
    """Lookup product in DB by name (and color if provided) and return enriched data.

    Used when Vision returns a name without price/photo.
    If color is provided, prefer color-specific matching.
    """
    try:
        catalog = CatalogService()

        def _norm(s: str) -> str:
            return " ".join((s or "").lower().strip().split())

        def _base_name(s: str) -> str:
            s = (s or "").strip()
            if "(" in s:
                return s.split("(")[0].strip()
            return s

        # Avoid duplicating color if already in the name.
        search_query = product_name
        if (
            color
            and f"({color})" not in product_name.lower()
            and color.lower() not in product_name.lower()
        ):
            # Try exact match with color.
            search_query = f"{product_name} ({color})"

        results = await catalog.search_products(query=search_query, limit=5)

        if not results:
            all_rows = await catalog.get_products_for_vision()
            target = _norm(product_name)
            target_base = _norm(_base_name(product_name))
            color_norm = _norm(color or "")

            scored: list[tuple[int, dict[str, Any]]] = []
            for row in all_rows or []:
                name = str(row.get("name") or "")
                n = _norm(name)
                nb = _norm(_base_name(name))
                score = 0
                if n == target or nb == target_base:
                    score += 50
                if target and (target in n or n in target):
                    score += 15
                if target_base and (target_base in nb or nb in target_base):
                    score += 10
                if color_norm and color_norm in n:
                    score += 5
                if score > 0:
                    scored.append((score, row))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = [row for _score, row in scored[:5]]

        # If no full-name match, try base name without color.
        if not results and "(" in product_name:
            base_name = product_name.split("(")[0].strip()
            logger.debug("Retry search with base name: '%s'", base_name)
            results = await catalog.search_products(query=base_name, limit=5)

        # If color is provided, search products with that color.
        product = None
        if color and results:
            for p in results:
                p_name = p.get("name", "").lower()
                if color.lower() in p_name:
                    product = p
                    break

        def _extract_colors(row: dict[str, Any]) -> list[str]:
            raw = row.get("colors") or row.get("color") or []
            if isinstance(raw, list):
                return [str(x).strip() for x in raw if str(x).strip()]
            if isinstance(raw, str):
                return [raw.strip()] if raw.strip() else []
            return []

        color_options: list[str] = []
        if results:
            seen: set[str] = set()
            for r in results:
                for c in _extract_colors(r):
                    lc = c.lower()
                    if lc not in seen:
                        seen.add(lc)
                        color_options.append(c)

        # If no color-specific match, pick the first.
        if not product and results:
            product = results[0]

        if product:
            price_display = CatalogService.format_price_display(product)
            # Try multiple possible column names for photo URL
            photo_url = (
                product.get("photo_url")
                or product.get("image_url")
                or product.get("photo")
                or product.get("image")
                or ""
            )

            ambiguous_color = bool((not color) and len(color_options) >= 2)
            if ambiguous_color:
                photo_url = ""
                with suppress(Exception):
                    product["_color_options"] = color_options

            logger.info(
                "📦 Enriched from DB: %s (color=%s) -> %s, photo=%s",
                product_name,
                color,
                price_display,
                photo_url[:50] if photo_url else "<no photo>",
            )
            return {
                "id": product.get("id", 0),
                "name": product.get("name", product_name),
                "price": CatalogService.get_price_for_size(product),
                "price_display": price_display,
                "color": ""
                if ambiguous_color
                else (
                    (product.get("colors") or [""])[0]
                    if isinstance(product.get("colors"), list)
                    else product.get("colors", "")
                ),
                "photo_url": photo_url,
                "description": product.get("description", ""),
                "_catalog_row": product,
                "_color_options": color_options,
                "_ambiguous_color": ambiguous_color,
            }
    except Exception as e:
        logger.warning("DB enrichment failed: %s", e)
    return None
