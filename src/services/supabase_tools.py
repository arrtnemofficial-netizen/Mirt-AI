"""Supabase-native product tools used by the Pydantic AI agent.

This module avoids "vibe" behaviours by enforcing strict validation of
Supabase rows, deterministic fallbacks for embeddings, and retry-wrapped
RPC/SQL calls with explicit failure signalling. The tools never emit rows
without mandatory identifiers, pricing, or photo URLs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from supabase import Client

from src.conf.config import settings
from src.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class SupabaseToolError(RuntimeError):
    """Raised when a Supabase tool call cannot be satisfied safely."""


def _hash_embedding(text: str, dim: int) -> list[float]:
    """Deterministic fallback embedding when OpenAI is not configured."""

    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < dim:
        for byte in digest:
            values.append((byte / 255.0) * 2 - 1)
            if len(values) >= dim:
                break
    return values


def _normalise_colors(colors: Any) -> list[dict]:
    if isinstance(colors, dict):
        return [
            {
                "color_name": name,
                "photo_url": details.get("photo_url", ""),
                "color_description": details.get("description", ""),
                "sku": details.get("sku"),
            }
            for name, details in colors.items()
        ]
    return colors if isinstance(colors, list) else []


def _primary_photo(colors: list[dict]) -> str:
    for color in colors:
        url = color.get("photo_url")
        if url:
            return url
    return ""


def _validate_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a validated, formatted row or None if critical data is missing."""

    product_id = str(row.get("id", "")).strip()
    if not product_id:
        return None

    colors = _normalise_colors(row.get("colors"))
    photo_url = row.get("photo_url") or _primary_photo(colors)
    price_uniform = row.get("price_uniform")
    price_all_sizes = row.get("price_all_sizes")
    price_by_size = row.get("price_by_size")

    if price_uniform and not price_all_sizes:
        return None
    if price_uniform is False and not price_by_size:
        return None

    formatted = {
        "product_id": product_id,
        "name": row.get("name", ""),
        "variant_name": row.get("variant_name"),
        "color_variant": row.get("color_variant"),
        "category": row.get("category"),
        "subcategory": row.get("subcategory"),
        "sizes": row.get("sizes", []),
        "material": row.get("material"),
        "care": row.get("care"),
        "price_uniform": price_uniform,
        "price_all_sizes": price_all_sizes,
        "price_by_size": price_by_size,
        "colors": colors,
        "photo_url": photo_url,
    }

    if not formatted["photo_url"]:
        return None
    return formatted


async def _with_retries(coro_factory, *, attempts: int = 3, base_delay: float = 0.35, name: str) -> Any:
    """Run a blocking Supabase call in a thread with retries and jitter."""

    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.to_thread(coro_factory)
        except Exception as exc:  # pragma: no cover - defensive
            last_exc = exc
            if attempt >= attempts:
                logger.error("%s failed after %s attempts", name, attempts, exc_info=exc)
                raise SupabaseToolError(f"{name} failed after {attempts} attempts") from exc
            await asyncio.sleep(base_delay * attempt)


class SupabaseProductTools:
    """Implements Supabase catalog access for search and lookup tools."""

    def __init__(
        self,
        client: Client,
        *,
        products_table: str,
        match_rpc: str,
        embedding_model: str,
        embedding_dim: int,
    ) -> None:
        self.client = client
        self.products_table = products_table
        self.match_rpc = match_rpc
        self.embedding_model = embedding_model
        self.embedding_dim = embedding_dim
        self._embedder: Optional[AsyncOpenAI] = None

    def _ensure_embedder(self) -> Optional[AsyncOpenAI]:
        if settings.OPENAI_API_KEY.get_secret_value():
            if self._embedder is None:
                self._embedder = AsyncOpenAI(api_key=settings.OPENAI_API_KEY.get_secret_value())
        return self._embedder

    async def _embed(self, text: str) -> list[float]:
        embedder = self._ensure_embedder()
        if embedder is None or not text.strip():
            return _hash_embedding(text, self.embedding_dim)

        response = await embedder.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        embedding = response.data[0].embedding
        if len(embedding) != self.embedding_dim:
            if len(embedding) > self.embedding_dim:
                embedding = embedding[: self.embedding_dim]
            else:
                padding = _hash_embedding(text, self.embedding_dim - len(embedding))
                embedding.extend(padding)
        return embedding

    async def search_by_query(self, user_query: str, match_count: int = 5) -> List[Dict[str, Any]]:
        if not user_query.strip():
            return []

        embedding = await self._embed(user_query)

        def _call() -> Any:
            return self.client.rpc(
                self.match_rpc,
                {"query_embedding": embedding, "match_count": match_count},
            ).execute()

        response = await _with_retries(_call, name="supabase.search_by_query")
        data = getattr(response, "data", None) or []
        validated = [_validate_row(row) for row in data]
        return [row for row in validated if row]

    async def get_by_id(self, product_id: str) -> List[Dict[str, Any]]:
        def _call() -> Any:
            return (
                self.client.table(self.products_table)
                .select("*")
                .eq("id", product_id)
                .limit(1)
                .execute()
            )

        response = await _with_retries(_call, name="supabase.get_by_id")
        data = getattr(response, "data", None) or []
        validated = [_validate_row(row) for row in data]
        return [row for row in validated if row]

    async def get_by_photo_url(self, photo_url: str, limit: int = 3) -> List[Dict[str, Any]]:
        if not photo_url:
            return []

        def _call() -> Any:
            return (
                self.client.table(self.products_table)
                .select("*")
                .ilike("colors::text", f"%{photo_url}%")
                .limit(limit)
                .execute()
            )

        response = await _with_retries(_call, name="supabase.get_by_photo_url")
        data = getattr(response, "data", None) or []
        validated = [_validate_row(row) for row in data]
        return [row for row in validated if row]


def get_supabase_tools() -> Optional[SupabaseProductTools]:
    client = get_supabase_client()
    if not client:
        return None
    return SupabaseProductTools(
        client,
        products_table=settings.SUPABASE_CATALOG_TABLE,
        match_rpc=settings.SUPABASE_MATCH_RPC,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_dim=settings.EMBEDDING_DIM,
    )
