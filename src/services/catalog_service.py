"""
Catalog Service - Supabase implementation.
==========================================
Handles product search and retrieval from real database.
"""

from __future__ import annotations

import logging
from typing import Any

from src.services.supabase_client import get_supabase_client

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
        
        Uses word-by-word matching to find relevant products.
        """
        if not self.client:
            logger.warning("Supabase client not available, returning empty search")
            return []

        try:
            # Extract key search terms (model name like "Лагуна", "Мрія", "Ритм")
            query_lower = query.lower()
            
            # Known model names to match
            model_names = [
                "лагуна", "мрія", "ритм", "каприз", "валері", "мерея", "анна"
            ]
            
            # Find which model is mentioned
            found_model = None
            for model in model_names:
                if model in query_lower:
                    found_model = model
                    break
            
            logger.info("🔍 [CATALOG] Searching: query='%s', found_model='%s'", query, found_model)
            
            if found_model:
                # Search by model name (case insensitive)
                db_query = self.client.table("products").select("*")
                db_query = db_query.ilike("name", f"%{found_model}%")
            elif query:
                # Fallback: search by first word
                first_word = query.split()[0] if query.split() else query
                db_query = self.client.table("products").select("*")
                db_query = db_query.ilike("name", f"%{first_word}%")
            else:
                return []
            
            if category:
                db_query = db_query.eq("category", category)
                
            # Execute
            response = db_query.limit(limit).execute()
            results = response.data or []
            
            logger.info("🔍 [CATALOG] Found %d products", len(results))
            if results:
                logger.debug("🔍 [CATALOG] First result: %s", results[0].get("name"))
            
            return results

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
