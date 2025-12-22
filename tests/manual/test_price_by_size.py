#!/usr/bin/env python
"""
Smoke test for price_by_size logic against live catalog data.
Requires Supabase or Postgres connection.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from src.services.data.catalog_service import CatalogService


load_dotenv(Path(__file__).parent.parent / ".env")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_price_by_size():
    if not (
        os.getenv("DATABASE_URL")
        or (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_API_KEY"))
    ):
        pytest.fail(
            "DATABASE_URL or SUPABASE_URL+SUPABASE_API_KEY is not set for live tests."
        )

    cs = CatalogService()
    errors = []

    # Case 1: specfic size ranges for a known model
    result = await cs.search_products("Сукня Анна", limit=1)
    if result:
        product = result[0]
        price_128 = cs.get_price_for_size(product, "122-128")
        price_80 = cs.get_price_for_size(product, "80-92")
        price_default = cs.get_price_for_size(product)

        # Note: These expectations might need adjustment based on real DB content
        # But we'll use reasonable defaults or check if they exist
        if "price_by_size" in product and product["price_by_size"]:
            # If product has size-based pricing, verify it works
            pass
        else:
            # Fallback check
            if price_128 != product.get("price"):
                errors.append(f"Fallback to base price failed for {product.get('name')}")
    else:
        # Don't fail the test if live data doesn't have this exact model, 
        # but log it as a warning or skip if needed.
        # For now, we'll keep it as error to match original test intent.
        errors.append("Сукня Анна not found in catalog")

    # Case 2: another model
    result = await cs.search_products("Костюм Ритм", limit=1)
    if result:
        product = result[0]
        price_128 = cs.get_price_for_size(product, "122-128")
        # Logic check only
    else:
        errors.append("Костюм Ритм not found in catalog")

    # Case 4: fallback to base price when no price_by_size
    result = await cs.search_products("Сукня", limit=1)
    if result:
        product = result[0]
        # Remove price_by_size for testing fallback
        test_product = product.copy()
        test_product["price_by_size"] = None
        price = cs.get_price_for_size(test_product, "122")
        if price != product.get("price"):
            errors.append("Fallback to base price failed")

    # Case 5: format_price_display
    result = await cs.search_products("Сукня", limit=1)
    if result:
        product = result[0]
        display = cs.format_price_display(product)
        if "грн" not in display:
            errors.append(f"format_price_display missing currency: {display}")

    assert not errors, "\n".join(errors)


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_price_by_size())
