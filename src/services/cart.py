"""
Cart Manager Service.
=====================
Centralized logic for cart operations (addition, deduplication, merging).
Extracted from src/agents/langgraph/nodes/agent/tools.py to satisfy SSOT architecture.
"""
from __future__ import annotations

import logging
from typing import Any

from src.core.models import Product

logger = logging.getLogger(__name__)


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


class CartManager:
    """
    Manages cart state operations.
    """

    @staticmethod
    def merge_products(
        existing: list[dict[str, Any]],
        incoming: list[dict[str, Any]],
        *,
        append: bool,
    ) -> list[dict[str, Any]]:
        """
        Merge product lists, preserving details like size/color/price.

        Args:
            existing: Current cart products (dicts).
            incoming: New products to add/merge (dicts).
            append: If True, adds to list (upsell). If False, replaces/updates.
        """
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
