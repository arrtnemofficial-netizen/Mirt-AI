"""Catalog loading and search helpers (JSON fallback for tests/offline).

The catalog is embedded in the system prompt (system_prompt_full.yaml).
This module provides JSON-based catalog access for tests and offline scenarios.

NOTE: Production uses Embedded Catalog in prompt. RAG/Supabase tools removed.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.models import Product


if TYPE_CHECKING:
    from collections.abc import Sequence


CATALOG_PATH = Path("data/catalog.json")


class CatalogService:
    """Load and search the product catalog."""

    def __init__(self, path: Path = CATALOG_PATH):
        self.path = path
        self._products: list[Product] = self._load()

    def _load(self) -> list[Product]:
        if not self.path.exists():
            raise FileNotFoundError(f"Catalog file not found: {self.path}")

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        products = [Product(**item) for item in raw]
        return products

    def search(self, query: str, limit: int = 10) -> list[Product]:
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

    def search_dicts(self, query: str, limit: int = 10) -> list[dict]:
        """Convenience wrapper for agent tools (returns plain dicts)."""

        return [product.model_dump() for product in self.search(query, limit)]

    @property
    def products(self) -> Sequence[Product]:
        return tuple(self._products)


@lru_cache(maxsize=1)
def get_catalog() -> CatalogService:
    """Cached catalog instance for runtime use (JSON-based, for tests/offline)."""
    return CatalogService()
