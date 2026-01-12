
"""
Cart Handler.
=============
Responsible for managing the selected products list (cart).
Handles:
1. Merging new products from LLM into existing cart.
2. Deduplication (Delegates to SSOT helper).
3. Strict Additive Mode (for Payment Phase safety).
"""

import logging
from typing import Any

from src.agents.langgraph.rules.cart_intent import detect_add_to_cart
from src.agents.langgraph.nodes.helpers.vision.product_deduplication import add_product_safely

logger = logging.getLogger(__name__)


def merge_cart(
    current_products: list[dict[str, Any]],
    new_products: list[dict[str, Any]],
    user_text: str,
    strict_mode: bool = False,
) -> list[dict[str, Any]]:
    """
    Merge new products into the current cart with smart deduplication.

    Args:
        current_products: Existing products in state.
        new_products: Products returned by LLM in this turn.
        user_text: User's message text (for intent detection).
        strict_mode: If True (e.g., Payment State), only adds products if
                     there is an EXPLICIT 'add to cart' intent.

    Returns:
        Updated list of products.
    """
    if not new_products:
        return current_products or []

    # 1. Check intent via SSOT rule
    user_text_lower = user_text.lower()
    has_explicit_add_intent = detect_add_to_cart(user_text_lower)

    should_append = False

    if strict_mode:
        # In strict mode (Payment State), we are paranoid.
        if has_explicit_add_intent and current_products:
            should_append = True
            logger.info("🛒 Cart Handler: Strict Mode - Appending products (explicit intent found).")
        else:
            logger.info(
                "🛒 Cart Handler: Strict Mode - Ignoring %d products (no explicit add intent).",
                len(new_products),
            )
            return current_products or []
    else:
        # Normal mode: Append if explicit add intent, otherwise replace if new products found.
        # Logic: functional replace vs append.
        should_append = bool(current_products) and has_explicit_add_intent

    # 2. Merge logic using SSOT Helper
    if should_append:
        # Start with copy of current
        merged = list(current_products)
        
        # Add each new product safely
        for new_item in new_products:
            merged, added = add_product_safely(
                new_product=new_item,
                existing_products=merged,
                strict_duplicate_check=True,  # Strict check for cart
                session_id="HANDLER"
            )
        return merged
    else:
        # Replace mode
        logger.info(
            "🛒 Cart Handler: Replaced cart (prev=%d) with new selection (%d)",
            len(current_products or []),
            len(new_products),
        )
        # However, we should still deduplicate the new list itself!
        # e.g. LLM returns [A, A] -> [A]
        unique_new = []
        for item in new_products:
            unique_new, _ = add_product_safely(item, unique_new, strict_duplicate_check=True, session_id="HANDLER")
        return unique_new
