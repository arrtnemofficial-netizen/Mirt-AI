"""
Agent Tools - Pure logic helpers.
================================
Contains stateless functions for:
- Data merging (products)
- Regex extraction (size, height)
- Math calculations
"""
from __future__ import annotations

import re
import logging
from functools import lru_cache
from typing import Any

from src.agents.langgraph.nodes.utils import get_size_and_price_for_height
from src.core.prompt_registry import load_yaml_from_registry
from src.core.registry_keys import SystemKeys

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def _get_size_patterns() -> list[str]:
    data = load_yaml_from_registry(SystemKeys.TEXTS.value)
    patterns = data.get("size_patterns", []) if isinstance(data, dict) else []
    return [str(p) for p in patterns if p]


def merge_product_fields(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge product dicts while preserving non-empty existing fields."""
    merged = dict(existing)
    for key, new_value in incoming.items():
        if key == "price":
            # Update price if new value is valid, or if we didn't have one
            if (isinstance(new_value, (int, float)) and new_value > 0) or key not in merged:
                merged[key] = new_value
            continue
        if key in {"size", "color", "photo_url", "description"}:
            # Update text fields if new value is present, or if we didn't have one
            if (isinstance(new_value, str) and new_value.strip()) or key not in merged:
                merged[key] = new_value
            continue
        # Default overwrite
        merged[key] = new_value
    return merged


def product_match_key(item: dict[str, Any]) -> str:
    """Stable key for product matching (id preferred, else name)."""
    pid = item.get("id")
    if isinstance(pid, int) and pid > 0:
        return f"id:{pid}"
    name = str(item.get("name") or "").strip().lower()
    return f"name:{name}" if name else ""


def merge_products(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    append: bool,
) -> list[dict[str, Any]]:
    """Merge product lists, preserving details like size/color/price."""
    by_id: dict[int, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for item in existing:
        pid = item.get("id")
        name = str(item.get("name") or "").strip().lower()
        if isinstance(pid, int) and pid > 0:
            by_id[pid] = item
        if name:
            by_name[name] = item

    merged_existing = list(existing)
    merged_incoming: list[dict[str, Any]] = []
    
    for item in incoming:
        pid = item.get("id")
        name = str(item.get("name") or "").strip().lower()
        existing_item = None
        
        # Try finding match
        if isinstance(pid, int) and pid > 0:
            existing_item = by_id.get(pid)
        if existing_item is None and name:
            existing_item = by_name.get(name)
            
        # Merge or add new
        merged_incoming.append(
            merge_product_fields(existing_item or {}, item) if existing_item else item
        )

    if not append:
        return merged_incoming

    # Append mode: join both lists but deduplicate exact matches
    seen_keys: set[str] = set()
    result: list[dict[str, Any]] = []
    
    for item in [*merged_existing, *merged_incoming]:
        # Generate a very specific key including size/color to allow
        # the same product with DIFFERENT attributes to exist (e.g. diff sizes)
        pid = item.get("id")
        name = str(item.get("name") or "").strip().lower()
        size = str(item.get("size") or "").strip().lower()
        color = str(item.get("color") or "").strip().lower()
        
        key_base = f"id:{pid}" if pid else f"name:{name}"
        unique_key = f"{key_base}|size:{size}|color:{color}"
        
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        result.append(item)
        
    return result


def apply_height_to_products(
    products: list[dict[str, Any]],
    height_cm: int,
) -> list[dict[str, Any]]:
    """Apply size to products when height is known but size is missing."""
    if not products:
        return products

    size_label, _ = get_size_and_price_for_height(height_cm)
    updated = [dict(p) for p in products]
    for product in updated:
        if not product.get("size"):
            product["size"] = size_label
    return updated


def extract_size_from_response(messages: list) -> str | None:
    """
    Extract size from LLM response messages.

    Fallback when LLM forgets to include size in products[].
    Looks for size patterns from registry.
    """
    patterns = _get_size_patterns()
    for msg in messages:
        content = msg.content if hasattr(msg, "content") else str(msg)

        for pattern in patterns:
            # Use re.IGNORECASE for proper Unicode handling
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                size = match.group(1)
                # Normalize dash
                size = size.replace("–", "-")
                logger.debug("Extracted size '%s' from: %s", size, content[:50])
                return size

    return None


# validate_phone_number moved to src.services.domain.payment.payment_validation
