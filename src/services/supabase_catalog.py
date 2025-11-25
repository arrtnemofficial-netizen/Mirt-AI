"""Supabase-backed catalog search with lightweight RAG-like retrieval."""
from __future__ import annotations

from typing import List, Optional

from supabase import Client

from src.core.models import Product
from src.services.supabase_client import get_supabase_client


class SupabaseCatalogService:
    """Catalog search that queries Supabase tables instead of local JSON."""

    def __init__(self, client: Client, table: str = "products") -> None:
        self.client = client
        self.table = table

    def search(self, query: str, limit: int = 10) -> List[Product]:
        normalized = query.strip()
        if not normalized:
            return []

        # Basic RAG retrieval: fetch by name/category match; table can be indexed
        response = (
            self.client.table(self.table)
            .select("*")
            .or_(
                f"name.ilike.%{normalized}%,category.ilike.%{normalized}%",
            )
            .limit(limit)
            .execute()
        )
        data = getattr(response, "data", None)  # type: ignore[attr-defined]
        if not data:
            return []
        return [Product(**row) for row in data]

    def search_dicts(self, query: str, limit: int = 10) -> List[dict]:
        return [product.model_dump() for product in self.search(query, limit)]


def get_supabase_catalog(table: str) -> Optional[SupabaseCatalogService]:
    client = get_supabase_client()
    if not client:
        return None
    return SupabaseCatalogService(client, table=table)

