"""
Product Name Matcher Service
============================

Normalizes product names from LLM to canonical catalog names.
"""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from src.core.prompt_registry import get_snippet_by_header


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CANONICAL_NAMES_PATH = PROJECT_ROOT / "data" / "vision" / "generated" / "canonical_names.json"


@lru_cache(maxsize=1)
def _load_canonical_names() -> dict:
    """Load canonical names mapping (cached)."""
    try:
        with open(CANONICAL_NAMES_PATH, encoding="utf-8") as f:
            data = json.load(f)
            return data.get("canonical_names", {})
    except FileNotFoundError:
        logger.warning(f"canonical_names.json not found at {CANONICAL_NAMES_PATH}")
        return {}


@lru_cache(maxsize=1)
def _get_valid_product_names() -> set:
    """Get set of valid canonical product names."""
    try:
        with open(CANONICAL_NAMES_PATH, encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("valid_product_names", []))
    except FileNotFoundError:
        return set()


def normalize_product_name(raw_name: str) -> str | None:
    """Normalize product name from LLM to canonical name."""
    if not raw_name:
        return None

    normalized = raw_name.strip().lower()
    if not normalized:
        return None

    canonical_map = _load_canonical_names()
    if normalized in canonical_map:
        return canonical_map[normalized]

    words = normalized.split()
    for i in range(len(words), 0, -1):
        partial = " ".join(words[:i])
        if partial in canonical_map:
            return canonical_map[partial]

    for key, value in canonical_map.items():
        if key in normalized or normalized in key:
            return value

    valid_names = _get_valid_product_names()
    for valid_name in valid_names:
        if valid_name.lower() in normalized or normalized in valid_name.lower():
            return valid_name

    logger.warning(f"Could not normalize product name: {raw_name}")
    return None


def _get_color_patterns() -> list[tuple[str, str]]:
    """Get color patterns from registry."""
    lines = get_snippet_by_header("COLOR_KEYS_MAPPING")
    patterns = []
    if not lines:
        return []
        
    # Standardize: flattened list of lines across all bubbles
    all_lines = []
    for b in lines:
        all_lines.extend(b.split("\n"))
        
    for line in all_lines:
        line = line.strip()
        if ":" in line:
            needle, canonical = line.split(":", 1)
            patterns.append((needle.strip(), canonical.strip()))
    return patterns


def extract_requested_color(text: str) -> str | None:
    """Extract color from text using registry patterns."""
    t = (text or "").lower().replace("\u0451", "\u0435")
    t = " ".join(t.split())

    patterns = _get_color_patterns()

    for needle, canonical in patterns:
        try:
            pattern = rf"\b{re.escape(needle)}\b"
            compiled = re.compile(pattern, re.IGNORECASE)
            if compiled.search(t):
                return canonical
        except re.error:
            # Skip invalid patterns
            continue
    return None


def is_valid_product_name(name: str) -> bool:
    """Check if name is a valid canonical product name."""
    valid_names = _get_valid_product_names()
    return name in valid_names


def extract_color_from_name(raw_name: str) -> str | None:
    """Extract color from product name if present."""
    patterns = _get_color_patterns()
    raw_lower = raw_name.lower()

    # Simple check for unique canonical colors from patterns
    unique_colors = {c for _, c in patterns}

    for color in unique_colors:
        if color in raw_lower:
            return color

    return None


def parse_product_response(raw_name: str) -> dict:
    """Parse LLM product name response into normalized parts."""
    result = {
        "raw": raw_name,
        "name": None,
        "color": None,
        "valid": False,
    }

    canonical_name = normalize_product_name(raw_name)
    if canonical_name:
        result["name"] = canonical_name
        result["valid"] = True

    color = extract_color_from_name(raw_name)
    if color:
        result["color"] = color

    return result


def reload_canonical_names():
    """Force reload canonical names (clears cache)."""
    _load_canonical_names.cache_clear()
    _get_valid_product_names.cache_clear()
    logger.info("Canonical names cache cleared")
