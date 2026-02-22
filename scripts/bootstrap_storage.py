#!/usr/bin/env python3
"""Bootstrap storage schema and seed products from canonical YAML.

Features:
- Creates products / agent_sessions / mirt_memories tables idempotently.
- Creates required indexes (session_id, expires_at, GIN JSONB).
- Upserts products from data/vision/products_master.yaml using ON CONFLICT.
- Supports --schema-only / --seed-products-only / --dry-run modes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import yaml
from psycopg.types.json import Json

CATALOG_PATH = Path("data/vision/products_master.yaml")


@dataclass(frozen=True)
class ProductSeedRow:
    sku: str
    name: str
    category: str
    subcategory: str | None
    sizes: list[str]
    colors: list[str]
    photo_url: str
    price_by_size: dict[str, int]
    visual_rules: dict[str, Any]
    distinction_rules: dict[str, Any]


class BootstrapError(Exception):
    """Structured operational error for bootstrap flow."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise BootstrapError(
            code="MISSING_DATABASE_URL",
            message="DATABASE_URL is not set",
            details={"hint": "Export DATABASE_URL before running bootstrap_storage.py"},
        )
    return url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap DB schema and seed products")
    parser.add_argument("--schema-only", action="store_true", help="Create/upgrade schema only")
    parser.add_argument("--seed-products-only", action="store_true", help="Upsert products only")
    parser.add_argument("--dry-run", action="store_true", help="Execute in transaction and rollback")
    args = parser.parse_args()

    if args.schema_only and args.seed_products_only:
        raise BootstrapError(
            code="INVALID_FLAGS",
            message="--schema-only and --seed-products-only cannot be used together",
            details={"flags": ["--schema-only", "--seed-products-only"]},
        )
    return args


def load_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.exists():
        raise BootstrapError(
            code="CATALOG_NOT_FOUND",
            message="Canonical products catalog not found",
            details={"path": str(CATALOG_PATH)},
        )

    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise BootstrapError(
            code="INVALID_CATALOG",
            message="Catalog root must be a mapping",
            details={"path": str(CATALOG_PATH)},
        )
    return data


def _get_display_color(color_name: str, color_info: dict[str, Any]) -> str:
    display_name = color_info.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        return display_name.strip()
    return color_name.strip()


def build_seed_rows(catalog: dict[str, Any]) -> list[ProductSeedRow]:
    products = catalog.get("products") or {}
    if not isinstance(products, dict):
        raise BootstrapError(code="INVALID_CATALOG", message="products must be a mapping")

    rows: list[ProductSeedRow] = []
    for product_key, product in products.items():
        if not isinstance(product, dict):
            raise BootstrapError(
                code="INVALID_PRODUCT_ENTRY",
                message="Product entry must be a mapping",
                details={"product_key": str(product_key)},
            )

        product_name = str(product.get("name") or "").strip()
        category = str(product.get("category") or "").strip()
        subcategory = product.get("subcategory")
        if isinstance(subcategory, str):
            subcategory = subcategory.strip() or None
        elif subcategory is not None:
            subcategory = str(subcategory)

        if not product_name or not category:
            raise BootstrapError(
                code="MISSING_PRODUCT_FIELDS",
                message="Each product requires non-empty name and category",
                details={"product_key": str(product_key)},
            )

        prices_by_size = product.get("prices_by_size") or {}
        if not isinstance(prices_by_size, dict) or not prices_by_size:
            raise BootstrapError(
                code="MISSING_PRICES",
                message="prices_by_size must be a non-empty mapping",
                details={"product_key": str(product_key)},
            )

        visual_rules = product.get("visual") or {}
        distinction_rules = product.get("distinction") or {}
        colors = product.get("colors") or {}

        if not isinstance(colors, dict) or not colors:
            raise BootstrapError(
                code="MISSING_COLORS",
                message="Each product must define at least one color",
                details={"product_key": str(product_key)},
            )

        for color_name, raw_color_info in colors.items():
            color_info = raw_color_info or {}
            if not isinstance(color_info, dict):
                raise BootstrapError(
                    code="INVALID_COLOR_ENTRY",
                    message="Color entry must be a mapping",
                    details={"product_key": str(product_key), "color": str(color_name)},
                )

            sku = str(color_info.get("sku") or "").strip()
            photo_url = str(color_info.get("photo_url") or "").strip() or None
            if not sku:
                raise BootstrapError(
                    code="MISSING_SKU",
                    message="SKU is required for each color variant",
                    details={"product_key": str(product_key), "color": str(color_name)},
                )

            sizes = color_info.get("sizes") or list(prices_by_size.keys())
            if not isinstance(sizes, list) or not sizes:
                raise BootstrapError(
                    code="MISSING_SIZES",
                    message="Sizes are required for each SKU",
                    details={"sku": sku},
                )

            normalized_sizes = [str(size).strip() for size in sizes if str(size).strip()]
            if not normalized_sizes:
                raise BootstrapError(
                    code="MISSING_SIZES",
                    message="Sizes cannot be empty after normalization",
                    details={"sku": sku},
                )

            filtered_prices: dict[str, int] = {}
            for size in normalized_sizes:
                if size in prices_by_size:
                    filtered_prices[size] = int(prices_by_size[size])

            if not filtered_prices:
                raise BootstrapError(
                    code="MISSING_PRICES_FOR_SKU",
                    message="No matching prices_by_size for SKU sizes",
                    details={"sku": sku, "sizes": normalized_sizes},
                )

            display_color = _get_display_color(str(color_name), color_info)
            row_name = f"{product_name} ({display_color})"
            rows.append(
                ProductSeedRow(
                    sku=sku,
                    name=row_name,
                    category=category,
                    subcategory=subcategory,
                    sizes=normalized_sizes,
                    colors=[str(color_name).strip()],
                    photo_url=photo_url,
                    price_by_size=filtered_prices,
                    visual_rules=visual_rules if isinstance(visual_rules, dict) else {},
                    distinction_rules=distinction_rules if isinstance(distinction_rules, dict) else {},
                )
            )

    return rows


def create_schema(cur: psycopg.Cursor[Any]) -> None:
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT NOT NULL,
            subcategory TEXT,
            sizes TEXT[] NOT NULL DEFAULT '{}',
            colors TEXT[] NOT NULL DEFAULT '{}',
            photo_url TEXT,
            sku TEXT UNIQUE,
            price_by_size JSONB,
            visual_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
            distinction_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            embedding VECTOR(1536)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_price_by_size_gin ON products USING GIN (price_by_size)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_visual_rules_gin ON products USING GIN (visual_rules)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_distinction_rules_gin ON products USING GIN (distinction_rules)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_sessions (
            session_id TEXT PRIMARY KEY,
            state JSONB NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_updated_at ON agent_sessions(updated_at)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS mirt_memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT NOT NULL,
            session_id TEXT,
            content TEXT NOT NULL,
            fact_type TEXT NOT NULL,
            category TEXT NOT NULL,
            importance FLOAT NOT NULL DEFAULT 0.5,
            surprise FLOAT NOT NULL DEFAULT 0.5,
            confidence FLOAT NOT NULL DEFAULT 0.8,
            metadata JSONB DEFAULT '{}'::jsonb,
            source TEXT DEFAULT 'conversation',
            ttl_days INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_accessed_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            embedding VECTOR(1536)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mirt_memories_session_id ON mirt_memories(session_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mirt_memories_expires_at ON mirt_memories(expires_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mirt_memories_metadata_gin ON mirt_memories USING GIN (metadata)")


def upsert_products(cur: psycopg.Cursor[Any], rows: list[ProductSeedRow]) -> int:
    statement = """
        INSERT INTO products (
            name,
            description,
            category,
            subcategory,
            sizes,
            colors,
            photo_url,
            sku,
            price_by_size,
            visual_rules,
            distinction_rules,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (sku) DO UPDATE
        SET name = EXCLUDED.name,
            category = EXCLUDED.category,
            subcategory = EXCLUDED.subcategory,
            sizes = EXCLUDED.sizes,
            colors = EXCLUDED.colors,
            photo_url = EXCLUDED.photo_url,
            price_by_size = EXCLUDED.price_by_size,
            visual_rules = EXCLUDED.visual_rules,
            distinction_rules = EXCLUDED.distinction_rules,
            updated_at = NOW()
    """

    for row in rows:
        cur.execute(
            statement,
            (
                row.name,
                None,
                row.category,
                row.subcategory,
                row.sizes,
                row.colors,
                row.photo_url,
                row.sku,
                Json(row.price_by_size),
                Json(row.visual_rules),
                Json(row.distinction_rules),
            ),
        )

    return len(rows)


def main() -> int:
    try:
        args = parse_args()
        database_url = get_database_url()

        should_schema = not args.seed_products_only
        should_seed = not args.schema_only

        seeded_rows = 0
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                if should_schema:
                    create_schema(cur)
                if should_seed:
                    catalog = load_catalog()
                    rows = build_seed_rows(catalog)
                    seeded_rows = upsert_products(cur, rows)

            if args.dry_run:
                conn.rollback()
                print(
                    json.dumps(
                        {
                            "status": "ok",
                            "dry_run": True,
                            "schema_applied": should_schema,
                            "products_upserted": seeded_rows,
                        },
                        ensure_ascii=False,
                    )
                )
                return 0

            conn.commit()

        print(
            json.dumps(
                {
                    "status": "ok",
                    "dry_run": False,
                    "schema_applied": should_schema,
                    "products_upserted": seeded_rows,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except BootstrapError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except psycopg.Error as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": "DATABASE_ERROR",
                    "message": str(exc).strip(),
                    "details": {
                        "sqlstate": exc.sqlstate,
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": "UNEXPECTED_ERROR",
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
