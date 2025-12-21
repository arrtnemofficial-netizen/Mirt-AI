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

    # Case 1: specific size ranges for a known model
    result = await cs.search_products("D>DøD3¥ŸD«Dø ¥?D_DDæDýD,D1", limit=1)
    if result:
        product = result[0]
        price_128 = cs.get_price_for_size(product, "122-128")
        price_80 = cs.get_price_for_size(product, "80-92")
        price_default = cs.get_price_for_size(product)

        if price_128 != 2190:
            errors.append(f"D>DøD3¥ŸD«Dø 122-128: expected 2190, got {price_128}")
        if price_80 != 1590:
            errors.append(f"D>DøD3¥ŸD«Dø 80-92: expected 1590, got {price_80}")
        if price_default != 1590:
            errors.append(f"D>DøD3¥ŸD«Dø default: expected 1590, got {price_default}")
    else:
        errors.append("D>DøD3¥ŸD«Dø not found in catalog")

    # Case 2: another model
    result = await cs.search_products("Do¥?¥-¥? DD_Dý¥,D,D1", limit=1)
    if result:
        product = result[0]
        price_128 = cs.get_price_for_size(product, "122-128")
        if price_128 != 2190:
            errors.append(f"Do¥?¥-¥? 122-128: expected 2190, got {price_128}")
    else:
        errors.append("Do¥?¥-¥? not found in catalog")

    # Case 3: 2 size bands
    result = await cs.search_products("DoDæ¥?Dæ¥?", limit=1)
    if result:
        product = result[0]
        price_128 = cs.get_price_for_size(product, "122-128")
        price_140 = cs.get_price_for_size(product, "134-140")
        if price_128 != 1985:
            errors.append(f"DoDæ¥?Dæ¥? 122-128: expected 1985, got {price_128}")
        if price_140 != 2150:
            errors.append(f"DoDæ¥?Dæ¥? 134-140: expected 2150, got {price_140}")
    else:
        errors.append("DoDæ¥?Dæ¥? not found in catalog")

    # Case 4: fallback to base price when no price_by_size
    result = await cs.search_products("D­¥ŸD§D«¥? D?D«D«Dø", limit=1)
    if result:
        product = result[0]
        price = cs.get_price_for_size(product, "122")
        if price != product.get("price"):
            errors.append("Fallback to base price failed")

    # Case 5: format_price_display includes discount logic
    result = await cs.search_products("D>DøD3¥ŸD«Dø", limit=1)
    if result:
        product = result[0]
        display = cs.format_price_display(product)
        if not ("1590" in display and "2390" in display):
            errors.append(f"format_price_display missing expected values: {display}")

    assert not errors, "\n".join(errors)


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_price_by_size())
