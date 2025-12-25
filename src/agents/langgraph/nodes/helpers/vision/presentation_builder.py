"""
Presentation Builder - Build beautiful product presentation text.
==================================================================
SSOT для формування красивої презентації продуктів:
1. snippets.md (пріоритет) → готові заготовки
2. products_master.yaml (visual) → texture_description, key_markers
3. Supabase description → fallback з шаблоном (не "Тканина: ...")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from .snippet_loader import get_product_snippet


def build_presentation_text(
    product_name: str,
    product_color: str | None = None,
    catalog_product: dict[str, Any] | None = None,
    yaml_product: dict[str, Any] | None = None,
) -> str | None:
    """
    Build beautiful presentation text for a product.
    
    IMPORTANT: Returns text ONLY if snippet exists in snippets.md.
    If no snippet found, returns None (no description bubble will be shown).
    
    Args:
        product_name: Product name (e.g., "Сукня Анна", "Костюм Лагуна")
        product_color: Color name (optional, for context)
        catalog_product: Product dict from Supabase catalog (optional, ignored)
        yaml_product: Product dict from products_master.yaml (optional, ignored)
    
    Returns:
        Beautiful presentation text from snippet (None if no snippet found)
    """
    # ONLY use snippets.md - no fallback to YAML or catalog description
    snippet_bubbles = get_product_snippet(product_name)
    if snippet_bubbles:
        # Use first snippet bubble as presentation
        return snippet_bubbles[0] if snippet_bubbles else None
    
    # No snippet found - return None (no description bubble)
    return None

