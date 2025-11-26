"""
Generate a catalog CSV with OpenAI embeddings (fallback hashing if API unavailable).

Usage:
  python scripts/catalog_to_csv.py [--out data/catalog.csv] [--model text-embedding-3-small]

If OPENAI_API_KEY is set, embeddings are requested from OpenAI. Otherwise a
stable hash-based vector is used so the pipeline can run offline, but you
should regenerate with a real key for production.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, List, Optional

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dep
    OpenAI = None  # type: ignore

CATALOG_PATH = Path("data/catalog.json")


def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def flatten_products(catalog) -> Iterable[dict]:
    if isinstance(catalog, list):
        for item in catalog:
            yield {
                "product_id": item.get("product_id"),
                "name": item.get("name"),
                "variant": item.get("variant_name") or item.get("color_variant"),
                "category": item.get("category"),
                "subcategory": item.get("subcategory"),
                "sizes": item.get("size") or item.get("sizes") or "",
                "material": item.get("material"),
                "price_uniform": item.get("price_uniform"),
                "price_all_sizes": item.get("price_all_sizes"),
                "price_by_size": json.dumps(item.get("price_by_size", {}), ensure_ascii=False),
                "color": item.get("color"),
                "color_description": item.get("color_description"),
                "photo_url": item.get("photo_url"),
                "sku": item.get("sku"),
            }
        return

    for category in catalog.values():
        products = category.get("products", {})
        for product_id, product in products.items():
            colors = product.get("colors", {}) or {None: {}}
            for color_name, color_data in colors.items():
                yield {
                    "product_id": product_id,
                    "name": product.get("name"),
                    "variant": product.get("variant_name") or product.get("color_variant"),
                    "category": product.get("category"),
                    "subcategory": product.get("subcategory"),
                    "sizes": ",".join(product.get("sizes", [])),
                    "material": product.get("material"),
                    "price_uniform": product.get("price_uniform"),
                    "price_all_sizes": product.get("price_all_sizes"),
                    "price_by_size": json.dumps(product.get("price_by_size", {}), ensure_ascii=False),
                    "color": color_name,
                    "color_description": color_data.get("description"),
                    "photo_url": color_data.get("photo_url"),
                    "sku": color_data.get("sku"),
                }


def hash_embed(text: str, dims: int = 64) -> List[float]:
    """Deterministic pseudo-embedding for offline use."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # repeat digest to fill dims*4 bytes
    buf = (digest * ((dims * 4 // len(digest)) + 1))[: dims * 4]
    vec = []
    for i in range(0, len(buf), 4):
        chunk = buf[i : i + 4]
        val = int.from_bytes(chunk, "big", signed=False)
        vec.append((val % 100000) / 100000.0)
    return vec


def get_client(api_key: Optional[str]) -> Optional[OpenAI]:
    if not api_key or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None


def embed_text(client: Optional[OpenAI], model: str, text: str) -> List[float]:
    if client is None:
        return hash_embed(text)
    try:
        resp = client.embeddings.create(model=model, input=text)
        return list(resp.data[0].embedding)
    except Exception:
        return hash_embed(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/catalog.csv")
    parser.add_argument("--model", default="text-embedding-3-small")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    client = get_client(api_key)

    catalog = load_catalog()
    rows = list(flatten_products(catalog))

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys()) + ["embedding_model", "embedding"] if rows else []

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            text_parts = [row.get("name") or "", row.get("variant") or "", row.get("category") or "", row.get("subcategory") or "", row.get("color") or "", row.get("color_description") or "", row.get("material") or ""]
            text = " | ".join(part for part in text_parts if part)
            embedding = embed_text(client, args.model, text)
            row["embedding_model"] = args.model if client else "hash://sha256-64d"
            row["embedding"] = json.dumps(embedding)
            writer.writerow(row)

    print(f"Wrote {len(rows)} rows to {output_path} using {'OpenAI' if client else 'hash'} embeddings")


if __name__ == "__main__":
    main()
