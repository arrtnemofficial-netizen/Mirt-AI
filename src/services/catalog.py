"""Catalog loading and search helpers (JSON fallback for tests/offline).

The catalog is kept outside of the prompt and exposed as a tool for the agent.
This module centralises validation and lightweight search logic so both the
agent and tests share identical behaviour.

NOTE: In production, use `supabase_tools.py` with vector embeddings for 
semantic search. This module is only for offline/test scenarios.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List, Sequence

from src.core.models import Product

CATALOG_PATH = Path("data/catalog.json")


class CatalogService:
    """Load and search the product catalog."""

    def __init__(self, path: Path = CATALOG_PATH):
        self.path = path
        self._products: List[Product] = self._load()

    def _load(self) -> List[Product]:
        if not self.path.exists():
            raise FileNotFoundError(f"Catalog file not found: {self.path}")

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        products = [Product(**item) for item in raw]
        return products

    def search(self, query: str, limit: int = 10) -> List[Product]:
        """Return products that match the query by name, category, color or SKU."""

        normalized = query.lower().strip()
        if not normalized:
            return []

        def matches(product: Product) -> bool:
            haystacks = [
                product.name.lower(),
                (product.category or "").lower(),
                product.color.lower(),
                (product.sku or "").lower(),
            ]
            return any(normalized in hay for hay in haystacks)

        filtered = [product for product in self._products if matches(product)]
        return filtered[:limit]

    def search_dicts(self, query: str, limit: int = 10) -> List[dict]:
        """Convenience wrapper for agent tools (returns plain dicts)."""

        return [product.model_dump() for product in self.search(query, limit)]

    @property
    def products(self) -> Sequence[Product]:
        return tuple(self._products)


@lru_cache(maxsize=1)
def get_catalog() -> CatalogService:
    """Cached catalog instance for runtime use (JSON-based, for tests/offline)."""
    return CatalogService()

