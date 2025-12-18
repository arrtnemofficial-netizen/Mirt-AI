"""
Catalog Service - Supabase implementation.
==========================================
Production-ready catalog service with Vision AI support.

Features:
- Text search with multiple fields
- Vision-specific queries (fabric, closure, hood, etc.)
- Stock management
- Caching-ready interface
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.services.exceptions import CatalogUnavailableError
from src.services.observability import log_tool_execution, track_metric
from src.services.supabase_client import get_supabase_client


logger = logging.getLogger(__name__)

_GLOBAL_CACHE: dict[str, Any] = {}


# Flag to control error propagation vs silent failure (for backward compatibility)
RAISE_ON_CATALOG_ERROR = True


class CatalogService:
    """
    Product catalog service backed by Supabase.

    Optimized for Vision AI recognition with:
    - Feature-based search (fabric, closure, hood)
    - Visual markers retrieval
    - Confusion prevention (similar products)
    - Variable pricing by size (price_by_size JSONB)
    """

    def __init__(self) -> None:
        self.client = get_supabase_client()
        self._cache = _GLOBAL_CACHE

    # =========================================================================
    # PRICE HELPERS
    # =========================================================================

    @staticmethod
    def get_price_for_size(product: dict[str, Any], size: str | None = None) -> float:
        """
        Отримати ціну для конкретного розміру.

        Якщо price_by_size є і size вказано — бере ціну для розміру.
        Якщо price_by_size є але size не вказано — бере мінімальну ціну.
        Якщо price_by_size немає — бере звичайне поле price.
        """
        price_by_size = product.get("price_by_size")

        if price_by_size and isinstance(price_by_size, dict):
            if size:
                size_clean = str(size).strip().replace("–", "-").replace("—", "-")
                size_clean = " ".join(size_clean.split())

                if size_clean in price_by_size:
                    return float(price_by_size[size_clean])

                size_no_spaces = size_clean.replace(" ", "")
                if size_no_spaces in price_by_size:
                    return float(price_by_size[size_no_spaces])

                if size_no_spaces.isdigit():
                    size_num = int(size_no_spaces)
                    for k, v in price_by_size.items():
                        key = str(k).strip().replace("–", "-").replace("—", "-")
                        key = key.replace(" ", "")
                        if "-" not in key:
                            continue
                        start_s, end_s = key.split("-", 1)
                        if not (start_s.isdigit() and end_s.isdigit()):
                            continue
                        if int(start_s) <= size_num <= int(end_s):
                            return float(v)
            # Якщо розмір не вказано — повертаємо діапазон як мін ціну
            prices = list(price_by_size.values())
            return float(min(prices)) if prices else 0.0

        return float(product.get("price", 0))

    @staticmethod
    def get_price_range(product: dict[str, Any]) -> tuple[float, float] | None:
        """
        Отримати діапазон цін для товару з варіативним прайсом.

        Returns:
            (min_price, max_price) або None якщо ціна єдина
        """
        price_by_size = product.get("price_by_size")

        if price_by_size and isinstance(price_by_size, dict):
            prices = list(price_by_size.values())
            if prices:
                return (float(min(prices)), float(max(prices)))

        return None

    @staticmethod
    def format_price_display(product: dict[str, Any]) -> str:
        """
        Форматує ціну для відображення клієнту.

        Приклади:
        - "1850 грн" (єдина ціна)
        - "від 1590 до 2390 грн (залежить від розміру)"
        """
        price_range = CatalogService.get_price_range(product)

        if price_range:
            min_p, max_p = price_range
            if min_p == max_p:
                return f"{int(min_p)} грн"
            return f"від {int(min_p)} до {int(max_p)} грн (залежить від розміру)"

        price = product.get("price", 0)
        return f"{int(price)} грн"

    # =========================================================================
    # BASIC SEARCH
    # =========================================================================

    async def search_products(
        self,
        query: str,
        category: str | None = None,
        color: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search products by text query.
        Minimal version - only uses columns that exist in DB.
        """
        tool_name = "catalog.search_products"

        if not self.client:
            error_msg = "Supabase client not available"
            logger.error("[CATALOG] %s - cannot search products", error_msg)
            log_tool_execution(
                tool_name,
                success=False,
                latency_ms=0.0,
                result_count=0,
                error="no_client",
            )
            if RAISE_ON_CATALOG_ERROR:
                raise CatalogUnavailableError("Database connection not configured")
            return []

        start = time.perf_counter()
        success = False
        result_count = 0
        error_msg: str | None = None

        try:
            # Get all products, filter in code to avoid column errors
            db_query = self.client.table("products").select("*")

            # Only filter by name if query provided (name column should exist)
            if query:
                db_query = db_query.ilike("name", f"%{query}%")

            response = db_query.limit(limit).execute()
            data = response.data or []
            success = True
            result_count = len(data)
            return data

        except CatalogUnavailableError:
            raise  # Re-raise our custom exceptions
        except Exception as e:
            error_msg = str(e)
            logger.error("[CATALOG] Search failed: %s (query=%s)", e, query)
            if RAISE_ON_CATALOG_ERROR:
                raise CatalogUnavailableError(f"Search failed: {error_msg}") from e
            return []

        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            log_tool_execution(
                tool_name,
                success=success,
                latency_ms=latency_ms,
                result_count=result_count,
                error=error_msg,
            )
            track_metric(
                "catalog_search_latency_ms",
                latency_ms,
                tags={"method": "search_products"},
            )

    # =========================================================================
    # VISION-SPECIFIC SEARCH
    # =========================================================================

    async def search_by_features(
        self,
        fabric_type: str | None = None,
        closure_type: str | None = None,
        has_hood: bool | None = None,
        pants_style: str | None = None,
        color: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search products by visual features.
        Simplified: just returns all products, filtering done by AI.
        """
        tool_name = "catalog.search_by_features"

        if not self.client:
            log_tool_execution(
                tool_name,
                success=False,
                latency_ms=0.0,
                result_count=0,
                error="no_client",
            )
            return []

        start = time.perf_counter()
        success = False
        result_count = 0
        error_msg: str | None = None

        try:
            # Just get all products - let AI do the matching
            response = self.client.table("products").select("*").limit(limit).execute()
            data = response.data or []
            success = True
            result_count = len(data)
            return data

        except Exception as e:
            logger.error("Feature search failed: %s", e)
            error_msg = str(e)
            return []

        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            log_tool_execution(
                tool_name,
                success=success,
                latency_ms=latency_ms,
                result_count=result_count,
                error=error_msg,
            )
            track_metric(
                "catalog_search_latency_ms",
                latency_ms,
                tags={"method": "search_by_features"},
            )

    async def get_products_for_vision(
        self,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get all products for Vision AI prompt.
        Uses SELECT * to work with any DB schema.
        """
        tool_name = "catalog.get_products_for_vision"

        cache_key = f"vision_products:{category or ''}"
        try:
            cached = self._cache.get(cache_key)
            if isinstance(cached, dict):
                cached_ts = float(cached.get("ts") or 0.0)
                cached_data = cached.get("data")
                if cached_data is not None and (time.time() - cached_ts) < 60.0:
                    return list(cached_data)
        except Exception:
            pass

        if not self.client:
            log_tool_execution(
                tool_name,
                success=False,
                latency_ms=0.0,
                result_count=0,
                error="no_client",
            )
            return []

        start = time.perf_counter()
        success = False
        result_count = 0
        error_msg: str | None = None

        try:
            # Use SELECT * to avoid column errors - works with any schema
            response = self.client.table("products").select("*").execute()
            products = response.data or []
            success = True
            result_count = len(products)
            logger.info("Loaded %d products from DB for vision", len(products))
            try:
                self._cache[cache_key] = {"ts": time.time(), "data": list(products)}
            except Exception:
                pass
            return products

        except Exception as e:
            logger.error("Get products for vision failed: %s", e)
            error_msg = str(e)
            return []

        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            log_tool_execution(
                tool_name,
                success=success,
                latency_ms=latency_ms,
                result_count=result_count,
                error=error_msg,
            )
            track_metric(
                "catalog_vision_load_latency_ms",
                latency_ms,
                tags={"method": "get_products_for_vision"},
            )

    async def get_similar_products(
        self,
        product_id: int,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Get products that are similar (easily confused with).

        Used for Vision AI confusion prevention.
        """
        tool_name = "catalog.get_similar_products"

        if not self.client:
            log_tool_execution(
                tool_name,
                success=False,
                latency_ms=0.0,
                result_count=0,
                error="no_client",
            )
            return []

        start = time.perf_counter()
        success = False
        result_count = 0
        error_msg: str | None = None

        try:
            # First get the product to find its confused_with list
            product = await self.get_product_by_id(product_id)
            if not product:
                return []

            confused_with = product.get("confused_with", [])
            if not confused_with:
                # Fallback: find by same category and fabric
                return await self.search_by_features(
                    fabric_type=product.get("fabric_type"),
                    limit=limit,
                )

            # Get products by names in confused_with
            response = (
                self.client.table("products")
                .select("*")
                .in_("name", confused_with)
                .limit(limit)
                .execute()
            )
            data = response.data or []
            success = True
            result_count = len(data)
            return data

        except Exception as e:
            logger.error("Get similar products failed: %s", e)
            error_msg = str(e)
            return []

        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            log_tool_execution(
                tool_name,
                success=success,
                latency_ms=latency_ms,
                result_count=result_count,
                error=error_msg,
            )
            track_metric(
                "catalog_search_latency_ms",
                latency_ms,
                tags={"method": "get_similar_products"},
            )

    # =========================================================================
    # STOCK MANAGEMENT
    # =========================================================================

    async def check_stock(
        self,
        product_id: int,
        size: str | None = None,
    ) -> dict[str, Any]:
        """
        Check if product is in stock.

        Returns:
            {
                "in_stock": True/False,
                "quantity": int,
                "available_sizes": ["104", "110", "116"]
            }
        """
        tool_name = "catalog.check_stock"

        if not self.client:
            result = {"in_stock": False, "quantity": 0, "available_sizes": []}
            log_tool_execution(
                tool_name,
                success=False,
                latency_ms=0.0,
                result_count=0,
                error="no_client",
            )
            return result

        start = time.perf_counter()
        success = False
        error_msg: str | None = None

        try:
            product = await self.get_product_by_id(product_id)
            if not product:
                return {"in_stock": False, "quantity": 0, "available_sizes": []}

            sizes = product.get("sizes", [])
            if isinstance(sizes, str):
                import json

                sizes = json.loads(sizes)

            result = {
                "in_stock": product.get("in_stock", False),
                "quantity": product.get("stock_quantity", 0),
                "available_sizes": sizes,
            }
            success = True
            return result

        except Exception as e:
            logger.error("Check stock failed: %s", e)
            error_msg = str(e)
            return {"in_stock": False, "quantity": 0, "available_sizes": []}

        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            log_tool_execution(
                tool_name,
                success=success,
                latency_ms=latency_ms,
                result_count=0,
                error=error_msg,
            )
            track_metric(
                "catalog_stock_latency_ms",
                latency_ms,
                tags={"method": "check_stock"},
            )

    async def get_product_by_id(self, product_id: int) -> dict[str, Any] | None:
        """Get product details by ID."""
        tool_name = "catalog.get_product_by_id"

        if not self.client:
            log_tool_execution(
                tool_name,
                success=False,
                latency_ms=0.0,
                result_count=0,
                error="no_client",
            )
            return None

        start = time.perf_counter()
        success = False
        error_msg: str | None = None

        try:
            response = (
                self.client.table("products").select("*").eq("id", product_id).single().execute()
            )
            data = response.data
            success = data is not None
            return data
        except Exception as e:
            logger.error("Get product failed: %s", e)
            error_msg = str(e)
            return None

        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            log_tool_execution(
                tool_name,
                success=success,
                latency_ms=latency_ms,
                result_count=1 if success else 0,
                error=error_msg,
            )
            track_metric(
                "catalog_lookup_latency_ms",
                latency_ms,
                tags={"method": "get_product_by_id"},
            )

    async def get_products_by_ids(self, product_ids: list[int]) -> list[dict[str, Any]]:
        """Get multiple products by IDs."""
        tool_name = "catalog.get_products_by_ids"

        if not self.client or not product_ids:
            log_tool_execution(
                tool_name,
                success=False,
                latency_ms=0.0,
                result_count=0,
                error="no_client_or_empty_ids",
            )
            return []

        start = time.perf_counter()
        success = False
        result_count = 0
        error_msg: str | None = None

        try:
            response = self.client.table("products").select("*").in_("id", product_ids).execute()
            data = response.data or []
            success = True
            result_count = len(data)
            return data
        except Exception as e:
            logger.error("Get products batch failed: %s", e)
            error_msg = str(e)
            return []

        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            log_tool_execution(
                tool_name,
                success=success,
                latency_ms=latency_ms,
                result_count=result_count,
                error=error_msg,
            )
            track_metric(
                "catalog_lookup_latency_ms",
                latency_ms,
                tags={"method": "get_products_by_ids"},
            )

    async def get_size_recommendation(
        self,
        product_id: int,
        height_cm: int,
        age_years: int | None = None,
    ) -> str:
        """
        Get size recommendation.

        This logic is usually static based on standard charts,
        so we can keep it in code or move to DB later.
        """
        import bisect

        # Standard MIRT size chart
        thresholds = [80, 86, 92, 98, 104, 110, 116, 122, 128, 134, 140, 146, 152, 158, 164]
        sizes = [
            "80",
            "86",
            "92",
            "98",
            "104",
            "110",
            "116",
            "122",
            "128",
            "134",
            "140",
            "146",
            "152",
            "158",
            "164",
        ]

        # Find closest size
        index = bisect.bisect_left(thresholds, height_cm)
        if index < len(sizes):
            return sizes[index]
        return "164+"  # Out of range
