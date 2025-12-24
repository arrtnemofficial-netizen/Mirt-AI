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
    
    Priority order:
    1. snippets.md (if exists for this product) → use it
    2. products_master.yaml (visual.texture_description + key_markers) → build from YAML
    3. Supabase description → format nicely (avoid "Тканина: ..." as raw line)
    
    Args:
        product_name: Product name (e.g., "Сукня Анна", "Костюм Лагуна")
        product_color: Color name (optional, for context)
        catalog_product: Product dict from Supabase catalog (optional)
        yaml_product: Product dict from products_master.yaml (optional)
    
    Returns:
        Beautiful presentation text (None if nothing found)
    """
    # PRIORITY 1: snippets.md (ready-made beautiful text)
    snippet_bubbles = get_product_snippet(product_name)
    if snippet_bubbles:
        # Use first snippet bubble as presentation
        return snippet_bubbles[0] if snippet_bubbles else None
    
    # PRIORITY 2: products_master.yaml (visual.texture_description + key_markers)
    if yaml_product:
        visual = yaml_product.get("visual", {})
        texture_desc = visual.get("texture_description", "").strip()
        key_markers = visual.get("key_markers", [])
        
        if texture_desc or key_markers:
            lines = []
            
            # First line: product name + color
            if product_color:
                lines.append(f"Це наш {product_name} у кольорі {product_color}")
            else:
                lines.append(f"Це наш {product_name}")
            
            # Second line: texture/feel
            if texture_desc:
                lines.append(texture_desc)
            
            # Third line: key features (1-2 markers)
            if key_markers:
                markers_text = ", ".join(key_markers[:2])
                if markers_text:
                    lines.append(markers_text)
            
            return " ".join(lines) if lines else None
    
    # PRIORITY 3: Supabase description (format nicely, avoid "Тканина: ..." as raw)
    if catalog_product:
        description = str(catalog_product.get("description") or "").strip()
        if description:
            # Check if description starts with "Тканина:" - format it nicely
            if description.lower().startswith("тканина:"):
                # Extract fabric info and format as natural sentence
                fabric_part = description[len("Тканина:"):].strip()
                if fabric_part:
                    # Build natural sentence instead of "Тканина: ..."
                    return f"Тканина {fabric_part.lower()}"
                else:
                    # Just fabric type without "Тканина:"
                    fabric_type = catalog_product.get("fabric_type", "").strip()
                    if fabric_type:
                        return f"Тканина {fabric_type.lower()}"
            else:
                # Description doesn't start with "Тканина:" - use as-is (first 1-2 sentences)
                sentences = []
                for sep in (".", "!", "?"):
                    if sep in description:
                        parts = [p.strip() for p in description.split(sep) if p.strip()]
                        if parts:
                            sentences = parts[:2]  # First 2 sentences
                            break
                
                if sentences:
                    return ". ".join(sentences).strip() + "."
                else:
                    # No sentence separators - use first 180 chars
                    return description[:180].rstrip()
    
    return None

