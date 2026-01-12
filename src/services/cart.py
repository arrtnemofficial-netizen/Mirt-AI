"""
Cart Service - Unified Cart Management.
=======================================
Single Source of Truth for product addition, deduplication, and cart merging.

Logic:
- Handles product addition to cart
- Performs intelligent deduplication (by ID or fuzzy Name/Size/Color match)
- Supports different merge strategies (Strict/Soft)
"""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

MergeStrategy = Literal["strict", "soft"]  # strict = exact match, soft = fuzzy match


class CartManager:
    """Unified manager for cart operations."""

    def __init__(self, session_id: str = ""):
        self.session_id = session_id

    def add_products(
        self,
        current_cart: list[dict[str, Any]],
        new_products: list[dict[str, Any]],
        strategy: MergeStrategy = "strict",
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Add new products to the cart with deduplication.

        Args:
            current_cart: Existing products in cart
            new_products: Products to add
            strategy: Deduplication strategy

        Returns:
            (updated_cart, added_count)
        """
        updated_cart = list(current_cart)  # Copy to avoid mutation
        added_count = 0

        for product in new_products:
            is_duplicate = self._is_duplicate(
                product, updated_cart, strategy=strategy
            )

            if is_duplicate:
                logger.info(
                    "[SESSION %s] Cart: Duplicate product skipped: '%s' (strategy=%s)",
                    self.session_id,
                    product.get("name"),
                    strategy,
                )
                continue

            updated_cart.append(product)
            added_count += 1
            logger.info(
                "[SESSION %s] Cart: Added product: '%s' (id=%s)",
                self.session_id,
                product.get("name"),
                product.get("id"),
            )

        return updated_cart, added_count

    def _is_duplicate(
        self,
        new_product: dict[str, Any],
        existing_products: list[dict[str, Any]],
        strategy: MergeStrategy = "strict",
    ) -> bool:
        """Check if product exists in cart."""
        new_key = self._get_product_key(new_product, strategy)

        for existing in existing_products:
            existing_key = self._get_product_key(existing, strategy)
            if new_key == existing_key:
                return True

        return False

    def _get_product_key(
        self, product: dict[str, Any], strategy: MergeStrategy
    ) -> str:
        """
        Generate comparison key for product.

        Key components: ID, Name, Size, Color.
        """
        # 1. ID Check (Strongest signal)
        pid = str(product.get("id") or "").strip()
        if pid and pid != "0":
            # If strictly matching by ID, checking size/color depends on business logic.
            # Usually ID is SKU specific (includes size/color).
            # If ID is generic (model ID), we need size/color.
            # For Mirt, let's assume ID is Model ID, so we need variants.
            pass

        # Normalization
        name = str(product.get("name") or "").strip().lower()
        size = str(product.get("size") or "").strip().lower()
        color = str(product.get("color") or "").strip().lower()

        if strategy == "strict":
            # Exact match of all fields
            return f"{pid}|{name}|{size}|{color}"
        else:
            # Soft match (Fuzzy) - ignore ID if missing, relaxed string matching
            # Useful for "I want that dress" vs "Dress Laguna"
            # For now, simplistic implementation
            return f"{name}|{size}|{color}"

    @staticmethod
    def merge_carts(
        cart_a: list[dict[str, Any]], cart_b: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Merge two carts removing duplicates."""
        # Simple merge using strict strategy
        manager = CartManager()
        merged, _ = manager.add_products(cart_a, cart_b, strategy="strict")
        return merged
