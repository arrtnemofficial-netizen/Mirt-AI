"""
Product Colors Helper - Extract colors from products_master.yaml.
==================================================================
SSOT для витягу кольорів та фото з products_master.yaml.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Cache для products_master.yaml (завантажується один раз)
_PRODUCTS_MASTER_CACHE: dict[str, Any] | None = None


def _load_products_master() -> dict[str, Any]:
    """Load products_master.yaml with caching."""
    global _PRODUCTS_MASTER_CACHE
    if _PRODUCTS_MASTER_CACHE is not None:
        return _PRODUCTS_MASTER_CACHE

    # Get project root using same approach as product_matcher.py
    # From: src/agents/langgraph/nodes/helpers/vision/product_colors.py
    # To root: 6 levels up (agents -> langgraph -> nodes -> helpers -> vision -> product_colors.py)
    # Same pattern as product_matcher.py: Path(__file__).parent.parent.parent from src/services/
    # For this file: 6 levels up from src/agents/langgraph/nodes/helpers/vision/
    project_root = Path(__file__).parent.parent.parent.parent.parent.parent
    yaml_path = project_root / "data" / "vision" / "products_master.yaml"
    
    # Fallback for Docker/production: try /app/data/vision/ (Docker WORKDIR is /app)
    if not yaml_path.exists():
        yaml_path_docker = Path("/app/data/vision/products_master.yaml")
        if yaml_path_docker.exists():
            yaml_path = yaml_path_docker
        else:
            # Last fallback: try relative to current working directory
            yaml_path = Path("data/vision/products_master.yaml")
    
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            _PRODUCTS_MASTER_CACHE = yaml.safe_load(f) or {}
        logger.info("Loaded products_master.yaml from %s: %d products", yaml_path, len(_PRODUCTS_MASTER_CACHE.get("products", {})))
    except Exception as e:
        logger.error("Failed to load products_master.yaml from %s: %s", yaml_path, e)
        _PRODUCTS_MASTER_CACHE = {}

    return _PRODUCTS_MASTER_CACHE


def get_product_colors(product_name: str) -> list[dict[str, str]]:
    """
    Get all colors with photo URLs for a product from products_master.yaml.
    
    Args:
        product_name: Product name (e.g., "Сукня Анна", "Костюм Лагуна")
    
    Returns:
        List of dicts with keys: "color" (name), "photo_url", "sku"
        Example: [{"color": "голубий", "photo_url": "https://...", "sku": "..."}, ...]
    """
    master = _load_products_master()
    products = master.get("products", {})
    
    # Normalize product name for matching (case-insensitive, remove extra spaces)
    product_name_norm = " ".join(product_name.strip().split()).lower()
    
    # Try to find product by name
    for product_key, product_data in products.items():
        if not isinstance(product_data, dict):
            continue
        
        product_name_in_yaml = product_data.get("name", "").strip().lower()
        if product_name_norm == product_name_in_yaml:
            colors_data = product_data.get("colors", {})
            if not isinstance(colors_data, dict):
                return []
            
            result = []
            for color_name, color_info in colors_data.items():
                if isinstance(color_info, dict):
                    photo_url = color_info.get("photo_url", "")
                    sku = color_info.get("sku", "")
                    if photo_url:  # Only include colors with photos
                        result.append({
                            "color": color_name,
                            "photo_url": photo_url,
                            "sku": sku,
                        })
            
            logger.info(
                "Found %d colors for product '%s'",
                len(result),
                product_name,
            )
            return result
    
    logger.warning("Product '%s' not found in products_master.yaml", product_name)
    return []


def get_color_photos_for_upsell(
    product_name: str,
    exclude_color: str | None = None,
    max_photos: int = 4,
    offset: int = 0,
) -> tuple[list[dict[str, str]], bool]:
    """
    Get color photos for upsell (excluding the color already purchased).
    Supports pagination via offset parameter.
    
    Args:
        product_name: Product name (e.g., "Сукня Анна")
        exclude_color: Color to exclude (the one already purchased)
        max_photos: Maximum number of photos to return (default: 4)
        offset: Offset for pagination (default: 0)
    
    Returns:
        Tuple of (list of color photos, has_more)
        - list: Up to max_photos color photos (excluding exclude_color, starting from offset)
        - has_more: True if there are more colors available after this batch
    """
    all_colors = get_product_colors(product_name)
    
    # Filter out the color already purchased
    if exclude_color:
        exclude_color_norm = exclude_color.lower().strip()
        filtered = [
            c for c in all_colors
            if c.get("color", "").lower().strip() != exclude_color_norm
        ]
    else:
        filtered = all_colors
    
    # Apply pagination: skip offset items, take max_photos
    paginated = filtered[offset:offset + max_photos]
    has_more = len(filtered) > offset + max_photos
    
    return paginated, has_more

