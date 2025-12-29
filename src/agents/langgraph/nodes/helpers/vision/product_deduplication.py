"""
Product Deduplication Utilities.
================================
Professional-grade product comparison and deduplication logic.

This module provides:
- Normalized product comparison (handles variations in name, color, size)
- Duplicate detection with fuzzy matching
- Product identity fingerprinting
"""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


def normalize_product_key(product: dict[str, Any]) -> str:
    """
    Create normalized key for product comparison.
    
    This creates a deterministic fingerprint for product identity.
    Products with the same normalized key are considered duplicates.
    
    Args:
        product: Product dict with name, color, size, etc.
    
    Returns:
        Normalized key string for comparison
    
    Examples:
        >>> normalize_product_key({"name": "Костюм Лагуна", "color": "рожевий", "size": "110"})
        'костюм лагуна|рожевий|110'
        >>> normalize_product_key({"name": "Костюм  Лагуна  ", "color": "  РОЖЕВИЙ  ", "size": "110"})
        'костюм лагуна|рожевий|110'
    """
    # Extract and normalize fields
    name = str(product.get("name") or "").strip().lower()
    color = str(product.get("color") or "").strip().lower()
    size = str(product.get("size") or "").strip().lower()

    # Normalize whitespace (multiple spaces → single space)
    name = " ".join(name.split())
    color = " ".join(color.split())
    size = " ".join(size.split())

    # Create deterministic key: name|color|size
    # Empty fields are represented as empty strings (not omitted)
    key = f"{name}|{color}|{size}"

    return key


def is_product_duplicate(
    new_product: dict[str, Any],
    existing_products: list[dict[str, Any]],
    *,
    strict: bool = True,
) -> bool:
    """
    Check if new_product is a duplicate of any existing product.
    
    Args:
        new_product: New product to check
        existing_products: List of existing products
        strict: If True, requires exact match (name+color+size).
                 If False, allows same name+color with different size.
    
    Returns:
        True if duplicate found, False otherwise
    
    Examples:
        >>> existing = [{"name": "Костюм Лагуна", "color": "рожевий", "size": "110"}]
        >>> new = {"name": "Костюм Лагуна", "color": "рожевий", "size": "110"}
        >>> is_product_duplicate(new, existing)
        True
        
        >>> new2 = {"name": "Костюм Лагуна", "color": "рожевий", "size": "116"}
        >>> is_product_duplicate(new2, existing, strict=True)
        False
        >>> is_product_duplicate(new2, existing, strict=False)
        True
    """
    if not existing_products:
        return False

    new_key = normalize_product_key(new_product)

    for existing in existing_products:
        existing_key = normalize_product_key(existing)

        if strict:
            # Exact match required
            if new_key == existing_key:
                logger.debug(
                    "Duplicate detected (strict): new='%s' matches existing='%s'",
                    new_key,
                    existing_key,
                )
                return True
        else:
            # Same name+color, size can differ
            new_parts = new_key.split("|")
            existing_parts = existing_key.split("|")

            if len(new_parts) >= 2 and len(existing_parts) >= 2:
                # Compare name and color (ignore size)
                if new_parts[0] == existing_parts[0] and new_parts[1] == existing_parts[1]:
                    logger.debug(
                        "Duplicate detected (fuzzy): new='%s' matches existing='%s' (same name+color)",
                        new_key,
                        existing_key,
                    )
                    return True

    return False


def add_product_safely(
    new_product: dict[str, Any],
    existing_products: list[dict[str, Any]],
    *,
    strict_duplicate_check: bool = True,
    session_id: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Add product to list with duplicate checking.
    
    This is the main function to use for product addition.
    It handles:
    - Duplicate detection
    - Logging
    - Validation
    
    Args:
        new_product: New product to add
        existing_products: List of existing products (will be copied, not modified)
        strict_duplicate_check: If True, requires exact match for duplicate detection
        session_id: Optional session ID for logging
    
    Returns:
        Tuple of (updated_products_list, was_added)
        - updated_products_list: New list with product added (if not duplicate)
        - was_added: True if product was added, False if duplicate
    
    Examples:
        >>> existing = [{"name": "Костюм Лагуна", "color": "рожевий"}]
        >>> new = {"name": "Костюм Мрія", "color": "жовтий"}
        >>> products, added = add_product_safely(new, existing)
        >>> len(products)
        2
        >>> added
        True
    """
    # Validate new product
    if not new_product:
        logger.warning("[SESSION %s] Attempted to add empty product", session_id or "?")
        return list(existing_products), False

    product_name = str(new_product.get("name") or "").strip()
    if not product_name:
        logger.warning("[SESSION %s] Attempted to add product without name", session_id or "?")
        return list(existing_products), False

    # Check for duplicates
    is_duplicate = is_product_duplicate(
        new_product,
        existing_products,
        strict=strict_duplicate_check,
    )

    if is_duplicate:
        logger.info(
            "[SESSION %s] Product addition skipped: duplicate detected. "
            "Product='%s' (normalized_key='%s')",
            session_id or "?",
            product_name,
            normalize_product_key(new_product),
        )
        return list(existing_products), False

    # Add product (create new list to avoid mutation)
    updated_products = list(existing_products)
    updated_products.append(new_product)

    logger.info(
        "[SESSION %s] Product added successfully. "
        "Existing=%d, New='%s', Total=%d",
        session_id or "?",
        len(existing_products),
        product_name,
        len(updated_products),
    )

    return updated_products, True

