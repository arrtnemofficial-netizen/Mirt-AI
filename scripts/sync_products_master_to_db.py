#!/usr/bin/env python3
"""
Sync products from data/vision/products_master.yaml into PostgreSQL.

Behavior:
- Drops the legacy price column (optional).
- Ensures price_by_size exists.
- Updates sizes/colors/photo_url/price_by_size for existing SKUs.
- Optionally inserts missing SKUs (best-effort names from YAML).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import yaml


CATALOG_PATH = Path("data/vision/products_master.yaml")


@dataclass(frozen=True)
class ProductRow:
    sku: str
    name: str
    category: str
    subcategory: str | None
    colors: list[str]
    sizes: list[str]
    photo_url: str
    price_by_size: dict[str, int]


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    return url


def _load_catalog() -> dict[str, Any]:
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _color_display_name(color_name: str, color_info: dict[str, Any]) -> str:
    display = color_info.get("display_name")
    if isinstance(display, str) and display.strip():
        return display.strip()
    return color_name


def _build_rows(catalog: dict[str, Any]) -> list[ProductRow]:
    products = catalog.get("products") or {}
    rows: list[ProductRow] = []

    for product in products.values():
        product_name = str(product.get("name") or "").strip()
        category = str(product.get("category") or "").strip()
        subcategory = product.get("subcategory")
        if isinstance(subcategory, str):
            subcategory = subcategory.strip()
        prices_by_size = product.get("prices_by_size") or {}
        if not isinstance(prices_by_size, dict) or not prices_by_size:
            raise ValueError(f"Missing prices_by_size for product: {product_name}")

        base_sizes = list(prices_by_size.keys())
        colors = product.get("colors") or {}
        for color_name, color_info in colors.items():
            color_info = color_info or {}
            sku = str(color_info.get("sku") or "").strip()
            photo_url = str(color_info.get("photo_url") or "").strip()
            if not sku:
                raise ValueError(f"Missing sku for {product_name} color {color_name}")

            sizes = color_info.get("sizes") or base_sizes
            if not isinstance(sizes, list) or not sizes:
                raise ValueError(f"Missing sizes for SKU {sku}")

            filtered_prices = {k: prices_by_size[k] for k in sizes if k in prices_by_size}
            if not filtered_prices:
                raise ValueError(f"price_by_size missing for SKU {sku}")

            display_color = _color_display_name(str(color_name), color_info)
            name = f"{product_name} ({display_color})" if product_name else display_color

            rows.append(
                ProductRow(
                    sku=sku,
                    name=name,
                    category=category,
                    subcategory=subcategory,
                    colors=[str(color_name)],
                    sizes=[str(s) for s in sizes],
                    photo_url=photo_url,
                    price_by_size=filtered_prices,
                )
            )

    return rows


def _sync_rows(rows: list[ProductRow], drop_price: bool, insert_missing: bool) -> None:
    db_url = _get_database_url()

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE public.products ADD COLUMN IF NOT EXISTS price_by_size jsonb")
            if drop_price:
                cur.execute("ALTER TABLE public.products DROP COLUMN IF EXISTS price")

            cur.execute("SELECT sku FROM public.products")
            existing = {r[0] for r in cur.fetchall() if r[0]}

            missing: list[str] = []
            for row in rows:
                price_json = json.dumps(row.price_by_size, ensure_ascii=False)
                if row.sku in existing:
                    cur.execute(
                        """
                        UPDATE public.products
                        SET sizes = %s,
                            colors = %s,
                            photo_url = %s,
                            price_by_size = %s::jsonb,
                            updated_at = NOW()
                        WHERE sku = %s
                        """,
                        (row.sizes, row.colors, row.photo_url, price_json, row.sku),
                    )
                else:
                    if not insert_missing:
                        missing.append(row.sku)
                        continue
                    cur.execute(
                        """
                        INSERT INTO public.products
                            (name, description, category, subcategory, sizes, colors, photo_url, sku, price_by_size)
                        VALUES
                            (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            row.name,
                            None,
                            row.category or None,
                            row.subcategory,
                            row.sizes,
                            row.colors,
                            row.photo_url,
                            row.sku,
                            price_json,
                        ),
                    )

            if missing:
                raise SystemExit(
                    "Missing SKUs in DB (run with --insert-missing if needed): "
                    + ", ".join(missing)
                )

        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-drop-price",
        action="store_true",
        help="Do not drop the legacy price column",
    )
    parser.add_argument(
        "--insert-missing",
        action="store_true",
        help="Insert missing SKUs (best-effort name from YAML)",
    )
    args = parser.parse_args()

    catalog = _load_catalog()
    rows = _build_rows(catalog)
    _sync_rows(rows, drop_price=not args.no_drop_price, insert_missing=args.insert_missing)
    print(f"Synced {len(rows)} SKU rows from products_master.yaml")


if __name__ == "__main__":
    main()
