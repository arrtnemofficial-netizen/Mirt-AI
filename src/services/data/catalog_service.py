"""
Catalog Service - Supabase implementation.
==========================================
Handles product search and retrieval from real database.
"""

from __future__ import annotations

import logging
from typing import Any

from src.services.core.exceptions import CatalogUnavailableError
from src.services.core.observability import log_tool_execution, track_metric
from src.services.infra.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


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
        
        TODO: Implement vector search when embeddings are ready.
        For now, uses simple text search on name/description.
        """
        if not self.client:
            logger.warning("Supabase client not available, returning empty search")
            return []

        try:
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
            return response.data or []

        except Exception as e:
            logger.error("Catalog search failed: %s", e)
            return []

    async def get_product_by_id(self, product_id: int) -> dict[str, Any] | None:
        """Get product details by ID."""
        if not self.client:
            return None

        try:
            response = (
                self.client.table("products")
                .select("*")
                .eq("id", product_id)
                .single()
                .execute()
            )
            return response.data
        except Exception as e:
            logger.error("Get product failed: %s", e)
            return None

    async def get_products_by_ids(self, product_ids: list[int]) -> list[dict[str, Any]]:
        """Get multiple products by IDs."""
        if not self.client or not product_ids:
            return []

        try:
            response = (
                self.client.table("products")
                .select("*")
                .in_("id", product_ids)
                .execute()
            )
            return response.data or []
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
