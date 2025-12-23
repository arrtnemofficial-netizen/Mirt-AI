"""
Catalog Service - Supabase implementation.
==========================================
Handles product search and retrieval from real database.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.services.core.exceptions import CatalogUnavailableError
from src.services.core.observability import log_tool_execution, track_metric
from src.services.infra.supabase_client import get_supabase_client
from src.conf.config import settings

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300  # 5 minutes


def _safe_cache_key(prefix: str, parts: list[str]) -> str:
    import hashlib

    raw = "|".join([prefix, *parts]).encode("utf-8", errors="ignore")
    return f"mirt:catalog:{prefix}:{hashlib.sha256(raw).hexdigest()[:24]}"


def _get_redis_client():
    """Best-effort Redis client for caching (fails open).
    
    Returns None if Redis is unavailable (expected in dev environments).
    All errors are logged for observability.
    """
    try:
        import redis

        redis_url = settings.REDIS_URL
        if not redis_url:
            return None
        client = redis.from_url(redis_url, decode_responses=True)
        client.ping()
        return client
    except (redis.ConnectionError, redis.TimeoutError, redis.RedisError) as e:
        logger.debug("[CATALOG:CACHE] Redis unavailable (expected in dev): %s", type(e).__name__)
        return None
    except Exception as e:
        logger.warning("[CATALOG:CACHE] Unexpected error connecting to Redis: %s", type(e).__name__)
        return None


def _cache_get_json(key: str) -> Any | None:
    """Get JSON value from cache (returns None if cache unavailable or key not found).
    
    All errors are logged for observability.
    """
    r = _get_redis_client()
    if not r:
        return None
    try:
        raw = r.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("[CATALOG:CACHE] Failed to decode cached JSON for key '%s': %s", key, type(e).__name__)
        return None
    except (redis.ConnectionError, redis.TimeoutError, redis.RedisError) as e:
        logger.debug("[CATALOG:CACHE] Redis error getting key '%s': %s", key, type(e).__name__)
        return None
    except Exception as e:
        logger.warning("[CATALOG:CACHE] Unexpected error getting cached key '%s': %s", key, type(e).__name__)
        return None


def _cache_set_json(key: str, value: Any, *, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
    """Set JSON value in cache (silently fails if cache unavailable - non-critical).
    
    All errors are logged for observability.
    """
    r = _get_redis_client()
    if not r:
        return
    try:
        r.setex(key, int(ttl_seconds), json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError) as e:
        logger.warning("[CATALOG:CACHE] Failed to serialize value for key '%s': %s", key, type(e).__name__)
    except (redis.ConnectionError, redis.TimeoutError, redis.RedisError) as e:
        logger.debug("[CATALOG:CACHE] Redis error setting key '%s': %s", key, type(e).__name__)
    except Exception as e:
        logger.warning("[CATALOG:CACHE] Unexpected error setting cached key '%s': %s", key, type(e).__name__)


class CatalogService:
    """
    Product catalog service backed by Supabase.
    """

    def __init__(self) -> None:
        self.client = get_supabase_client()

    async def search_products(
        self,
        query: str,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search products in catalog.
        
        Uses simple text search on name/description.
        Note: Vector search was considered but not implemented as we use embedded catalog (products stored in DB with full metadata).
        """
        if not self.client:
            logger.warning("Supabase client not available, returning empty search")
            return []

        try:
            cache_key = _safe_cache_key(
                "search",
                [
                    str(query or "").strip().lower(),
                    str(category or "").strip().lower(),
                    str(int(limit)),
                ],
            )
            cached = _cache_get_json(cache_key)
            if isinstance(cached, list):
                return cached

            # Start building query
            db_query = self.client.table("products").select("*")
            
            # Text search filter (ilike is case-insensitive)
            # We search in name OR description OR category
            if query:
                # Supabase doesn't support generic OR across columns easily in simple client
                # So we'll prioritize name search for now
                db_query = db_query.ilike("name", f"%{query}%")
            
            if category:
                db_query = db_query.eq("category", category)
                
            # Execute
            response = db_query.limit(limit).execute()
            data = response.data or []
            _cache_set_json(cache_key, data)
            return data

        except Exception as e:
            logger.error("Catalog search failed: %s", e)
            return []

    async def get_product_by_id(self, product_id: int) -> dict[str, Any] | None:
        """Get product details by ID."""
        if not self.client:
            return None

        try:
            cache_key = _safe_cache_key("product", [str(int(product_id))])
            cached = _cache_get_json(cache_key)
            if isinstance(cached, dict) and cached.get("id"):
                return cached

            response = (
                self.client.table("products")
                .select("*")
                .eq("id", product_id)
                .single()
                .execute()
            )
            data = response.data
            if data:
                _cache_set_json(cache_key, data)
            return data
        except Exception as e:
            logger.error("Get product failed: %s", e)
            return None

    async def get_products_by_ids(self, product_ids: list[int]) -> list[dict[str, Any]]:
        """Get multiple products by IDs."""
        if not self.client or not product_ids:
            return []

        try:
            ids = [int(i) for i in product_ids if isinstance(i, int) or str(i).isdigit()]
            ids = [i for i in ids if i > 0]
            if not ids:
                return []

            # Try per-item cache first
            cached_items: list[dict[str, Any]] = []
            missing: list[int] = []
            for pid in ids:
                cache_key = _safe_cache_key("product", [str(pid)])
                cached = _cache_get_json(cache_key)
                if isinstance(cached, dict) and cached.get("id"):
                    cached_items.append(cached)
                else:
                    missing.append(pid)

            if not missing:
                # Preserve requested order
                by_id = {int(it["id"]): it for it in cached_items if isinstance(it, dict) and it.get("id")}
                return [by_id[i] for i in ids if i in by_id]

            response = (
                self.client.table("products")
                .select("*")
                .in_("id", missing)
                .execute()
            )
            fresh = response.data or []
            for item in fresh:
                try:
                    pid = int(item.get("id"))
                except (ValueError, TypeError) as e:
                    logger.warning("[CATALOG] Invalid product ID in batch response: %s (type: %s)", item.get("id"), type(item.get("id")).__name__)
                    continue
                _cache_set_json(_safe_cache_key("product", [str(pid)]), item)

            combined = cached_items + fresh
            by_id = {int(it["id"]): it for it in combined if isinstance(it, dict) and it.get("id")}
            return [by_id[i] for i in ids if i in by_id]
        except Exception as e:
            logger.error("Get products batch failed: %s", e)
            return []

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
            "80", "86", "92", "98", "104", "110", "116", 
            "122", "128", "134", "140", "146", "152", "158", "164"
        ]

        # Find closest size
        index = bisect.bisect_left(thresholds, height_cm)
        if index < len(sizes):
            return sizes[index]
        return "164+"  # Out of range

    def get_price_for_size(self, product: dict[str, Any], size: str | None = None) -> float:
        """Get price for specific size, or base price."""
        if not product:
            return 0.0
            
        base_price = float(product.get("price", 0))
        if not size:
            return base_price
            
        price_by_size = product.get("price_by_size", {})
        if not isinstance(price_by_size, dict):
            return base_price
            
        # Try exact match or base price
        return float(price_by_size.get(size, base_price))

    def format_price_display(self, product: dict[str, Any]) -> str:
        """Format price or price range for display."""
        if not product:
            return "0 грн"
            
        base_price = product.get("price", 0)
        price_by_size = product.get("price_by_size", {})
        
        if not price_by_size or not isinstance(price_by_size, dict):
            return f"{int(base_price)} грн"
            
        prices = [float(p) for p in price_by_size.values()]
        if not prices:
            return f"{int(base_price)} грн"
            
        p_min = int(min(prices))
        p_max = int(max(prices))
        
        if p_min == p_max:
            return f"{p_min} грн"
            
        return f"{p_min} - {p_max} грн"
