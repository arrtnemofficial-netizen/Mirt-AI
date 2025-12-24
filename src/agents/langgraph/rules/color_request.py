"""
Color Request Detection Rules
=============================
Детекція запитів на показ кольорів (універсально для будь-якого стану).
"""

import re
from typing import Any


def detect_color_show_request(text: str) -> bool:
    """
    Detect if user wants to see color options (photos).
    
    Examples:
        - "покажи кольори"
        - "інші кольори"
        - "хоче інший колір"
        - "є інші кольори?"
        - "покажи інші"
        - "можна подивитись кольори"
    
    Args:
        text: User message text
        
    Returns:
        True if user wants to see color photos, False otherwise
    """
    if not text:
        return False
    
    text_lower = text.lower().strip()
    
    # Patterns that indicate user wants to see colors
    show_patterns = [
        r"покажи.*кольор",
        r"покажи.*інш",
        r"покажи.*ще",
        r"інш.*кольор",
        r"є.*інш.*кольор",
        r"можна.*подивитись.*кольор",
        r"можна.*побачити.*кольор",
        r"хочу.*подивитись.*кольор",
        r"хочу.*побачити.*кольор",
        r"скинь.*кольор",
        r"скинь.*фото.*кольор",
        r"покажи.*фото.*кольор",
        r"які.*кольор.*є",
        r"які.*кольор.*маєте",
        r"хоче.*інш.*кольор",
        r"хочу.*інш.*кольор",
        r"показати.*кольор",
        r"показати.*інш",
    ]
    
    # Check for explicit "yes" to color upsell question
    yes_patterns = [
        r"^так$",
        r"^да$",
        r"^ок$",
        r"^окей$",
        r"покажи",
        r"показати",
        r"хочу",
        r"так.*покажи",
        r"да.*покажи",
    ]
    
    # Check if this is a response to color upsell question
    # (context-dependent, but we can check for short affirmative responses)
    if len(text_lower.split()) <= 3:
        for pattern in yes_patterns:
            if re.search(pattern, text_lower):
                return True
    
    # Check for explicit color show requests
    for pattern in show_patterns:
        if re.search(pattern, text_lower):
            return True
    
    return False


def get_product_name_for_color_show(state: dict[str, Any]) -> str | None:
    """
    Extract product name from state for color gallery.
    
    Priority:
    1. selected_products[0].name (current selection)
    2. offered_products[0].name (recent offer)
    3. metadata.upsell_product_name (from payment upsell)
    4. metadata.last_product_name (fallback)
    
    Args:
        state: Current conversation state
        
    Returns:
        Product name or None if not found
    """
    # Try selected_products first
    selected = state.get("selected_products", [])
    if selected and isinstance(selected, list) and len(selected) > 0:
        first_product = selected[0]
        if isinstance(first_product, dict):
            product_name = first_product.get("name")
            if product_name:
                return str(product_name).strip()
    
    # Try offered_products
    offered = state.get("offered_products", [])
    if offered and isinstance(offered, list) and len(offered) > 0:
        first_product = offered[0]
        if isinstance(first_product, dict):
            product_name = first_product.get("name")
            if product_name:
                return str(product_name).strip()
    
    # Try metadata.upsell_product_name (from payment upsell)
    metadata = state.get("metadata", {})
    if isinstance(metadata, dict):
        upsell_name = metadata.get("upsell_product_name")
        if upsell_name:
            return str(upsell_name).strip()
        
        # Fallback to last_product_name
        last_name = metadata.get("last_product_name")
        if last_name:
            return str(last_name).strip()
    
    return None


def get_current_color_for_exclusion(state: dict[str, Any]) -> str | None:
    """
    Get current color to exclude from color gallery.
    
    Args:
        state: Current conversation state
        
    Returns:
        Color name or None
    """
    # Try selected_products first
    selected = state.get("selected_products", [])
    if selected and isinstance(selected, list) and len(selected) > 0:
        first_product = selected[0]
        if isinstance(first_product, dict):
            color = first_product.get("color")
            if color:
                return str(color).strip()
    
    # Try offered_products
    offered = state.get("offered_products", [])
    if offered and isinstance(offered, list) and len(offered) > 0:
        first_product = offered[0]
        if isinstance(first_product, dict):
            color = first_product.get("color")
            if color:
                return str(color).strip()
    
    return None

