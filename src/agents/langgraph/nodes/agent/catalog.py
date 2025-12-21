"""
Agent Catalog Interface.
=======================
Handles data access for products, stock, and availability.
Currently relies on state metadata (pre-fetched by Vision), 
but provides a clean interface for future DB calls.
"""
from __future__ import annotations

from typing import Any


def check_color_availability(
    requested_color: str,
    available_colors: list[str],
) -> tuple[bool, list[str]]:
    """
    Check if a requested color is in the available list.
    
    Returns:
        (is_available, normalized_options)
    """
    if not available_colors:
        return False, []

    def _norm(s: str) -> str:
        return " ".join((s or "").lower().strip().split())

    # Normalize options
    options = [str(c).strip() for c in available_colors if str(c).strip()]
    option_norms = {_norm(c) for c in options}
    
    # Check match
    is_available = bool(option_norms and (_norm(requested_color) in option_norms))
    
    return is_available, options


def get_upsell_products(
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    """Get products available for upsell from metadata."""
    return metadata.get("upsell_base_products", []) or []
