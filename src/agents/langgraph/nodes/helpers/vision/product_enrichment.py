"""
Product Enrichment - Enrich products from database catalog.

This module handles enrichment of vision-identified products with real data
from the catalog database (price, photo, description, color options).
Extracted from vision.py for better testability and maintainability.
"""

import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.agents.pydantic.models import ProductMatch

logger = logging.getLogger(__name__)


async def enrich_product_from_db(
    product_name: str, color: str | None = None
) -> dict[str, Any] | None:
    """Lookup product in DB by name (and color if provided) and return enriched data.

    Використовується, коли Vision повернув назву без ціни/фото.
    ВАЖЛИВО: Якщо є колір - шукає з кольором для точного match!

    Args:
        product_name: Product name to search for
        color: Optional color filter

    Returns:
        Enriched product dict or None if not found
    """
    try:
        from src.services.catalog import CatalogService

        catalog = CatalogService()

        def _norm(s: str) -> str:
            return " ".join((s or "").lower().strip().split())

        def _base_name(s: str) -> str:
            s = (s or "").strip()
            if "(" in s:
                return s.split("(")[0].strip()
            return s

        # Якщо колір вже в назві (наприклад "Костюм Ритм (рожевий)") - не дублюємо
        search_query = product_name
        if (
            color
            and f"({color})" not in product_name.lower()
            and color.lower() not in product_name.lower()
        ):
            # Спробуємо знайти точний match з кольором
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

        # Якщо не знайшли з повною назвою - спробуємо базову назву без кольору
        if not results and "(" in product_name:
            base_name = product_name.split("(")[0].strip()
            logger.debug("Retry search with base name: '%s'", base_name)
            results = await catalog.search_products(query=base_name, limit=5)

        def _extract_colors(row: dict[str, Any]) -> list[str]:
            """Extract color options from product row."""
            raw = row.get("colors") or row.get("color") or []
            if isinstance(raw, list):
                return [str(x).strip() for x in raw if str(x).strip()]
            if isinstance(raw, str):
                return [raw.strip()] if raw.strip() else []
            return []

        # If color was provided, try to pick the best match by color.
        product: dict[str, Any] | None = None
        matched_by_color = False
        color_norm = _norm(color or "")
        if color_norm and results:
            for p in results:
                p_name = _norm(p.get("name", ""))
                if color_norm in p_name:
                    product = p
                    matched_by_color = True
                    break
                for c in _extract_colors(p):
                    if color_norm == _norm(c):
                        product = p
                        matched_by_color = True
                        break
                if product:
                    break

        color_options: list[str] = []
        if results:
            seen: set[str] = set()
            for r in results:
                for c in _extract_colors(r):
                    lc = c.lower()
                    if lc not in seen:
                        seen.add(lc)
                        color_options.append(c)

        # If still no product selected, nothing to enrich.
        if not product and results:
            product = results[0]
        if not product:
            return None

        price_display = CatalogService.format_price_display(product)
        # Try multiple possible column names for photo URL
        photo_url = (
            product.get("photo_url")
            or product.get("image_url")
            or product.get("photo")
            or product.get("image")
            or ""
        )

        color_mismatch = bool(color_norm and results and (not matched_by_color))
        ambiguous_color = bool(((not color_norm) and len(color_options) >= 2) or color_mismatch)

        if ambiguous_color:
            photo_url = ""
            with suppress(Exception):
                product["_color_options"] = color_options

        logger.info(
            "📦 Enriched from DB: %s (color=%s, mismatch=%s) -> %s, photo=%s",
            product_name,
            color,
            color_mismatch,
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
                if isinstance(product.get("colors"), str)
                else product.get("color", "")
                if isinstance(product.get("color"), str)
                else product.get("color", "")
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

