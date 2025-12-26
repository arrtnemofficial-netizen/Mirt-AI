"""
Product Name Matcher Service
============================

Нормалізує назви продуктів від LLM до канонічних назв з каталогу.
Захищає від варіацій типу:
- "Костюм Лагуна рожевий" → "Костюм Лагуна"
- "лагуна" → "Костюм Лагуна"
- "Лагуна" → "Костюм Лагуна"

Використовує canonical_names.json, згенерований з products_master.yaml
"""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path


logger = logging.getLogger(__name__)

# Path to canonical names - все в data/vision/
PROJECT_ROOT = Path(__file__).resolve().parents[3]
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
    """
    Normalize product name from LLM to canonical name.

    Args:
        raw_name: Raw product name from LLM (may include color, variations)

    Returns:
        Canonical product name or None if not found

    Examples:
        >>> normalize_product_name("Костюм Лагуна рожевий")
        "Костюм Лагуна"
        >>> normalize_product_name("лагуна")
        "Костюм Лагуна"
        >>> normalize_product_name("МРІЯ")
        "Костюм Мрія"
    """
    if not raw_name:
        return None

    # Normalize input
    normalized = raw_name.strip().lower()

    # Empty after strip = invalid
    if not normalized:
        return None

    canonical_map = _load_canonical_names()

    # Direct match
    if normalized in canonical_map:
        return canonical_map[normalized]

    # Try removing extra words (colors, etc.)
    # Split and try progressively shorter prefixes
    words = normalized.split()
    for i in range(len(words), 0, -1):
        partial = " ".join(words[:i])
        if partial in canonical_map:
            return canonical_map[partial]

    # Try fuzzy match - check if any canonical key is contained
    for key, value in canonical_map.items():
        if key in normalized or normalized in key:
            return value

    # Last resort - check valid names directly
    valid_names = _get_valid_product_names()
    for valid_name in valid_names:
        if valid_name.lower() in normalized or normalized in valid_name.lower():
            return valid_name

    logger.warning(f"Could not normalize product name: {raw_name}")
    return None


def extract_requested_color(text: str) -> str | None:
    t = (text or "").lower().replace("ё", "е")
    t = " ".join(t.split())

    patterns: list[tuple[str, str]] = [
        ("чорний", "чорний"),
        ("черный", "чорний"),
        ("білий", "білий"),
        ("белый", "білий"),
        ("сірий", "сірий"),
        ("серый", "сірий"),
        ("червоний", "червоний"),
        ("красный", "червоний"),
        ("червона", "червоний"),
        ("малина", "малина"),
        ("рожевий", "рожевий"),
        ("розовый", "рожевий"),
        ("голубий", "голубий"),
        ("голубой", "голубий"),
        ("блакитний", "голубий"),
        ("синій", "синій"),
        ("синий", "синій"),
        ("темно синій", "темно-синій"),
        ("темно-синій", "темно-синій"),
        ("темно синий", "темно-синій"),
        ("темно-синий", "темно-синій"),
        ("зелений", "зелений"),
        ("зеленый", "зелений"),
        ("зеленый", "зелений"),
        ("жовтий", "жовтий"),
        ("желтый", "жовтий"),
        ("помаранчевий", "помаранчевий"),
        ("оранжевый", "помаранчевий"),
        ("фіолетовий", "фіолетовий"),
        ("фиолетовый", "фіолетовий"),
        ("шоколад", "шоколад"),
        ("коричневий", "шоколад"),
        ("коричневый", "шоколад"),
        ("бордовий", "бордовий"),
        ("бордовый", "бордовий"),
        ("молочний", "молочний"),
        ("молочный", "молочний"),
        ("капучіно", "капучіно"),
        ("капучино", "капучіно"),
        ("бежевий", "бежевий"),
        ("бежевый", "бежевий"),
        ("лео", "лео"),
        ("леопард", "лео"),
    ]

    for needle, canonical in patterns:
        if re.search(rf"\b{re.escape(needle)}\b", t, flags=re.IGNORECASE):
            return canonical
    return None


def is_valid_product_name(name: str) -> bool:
    """Check if name is a valid canonical product name."""
    valid_names = _get_valid_product_names()
    return name in valid_names


def extract_color_from_name(raw_name: str) -> str | None:
    """
    Extract color from product name if present.

    Args:
        raw_name: Raw product name like "Костюм Лагуна рожевий"

    Returns:
        Color string or None
    """
    # Known colors from catalog
    KNOWN_COLORS = {
        "голубий",
        "малина",
        "чорний",
        "червоний",
        "шоколад",
        "рожевий",
        "сірий",
        "універсальний",
        "бордовий",
        "помаранчевий",
        "жовтий",
        "молочний",
        "капучіно",
        "темно синій",
        "темно-синій",
    }

    raw_lower = raw_name.lower()

    for color in KNOWN_COLORS:
        if color in raw_lower:
            return color

    return None


def parse_product_response(raw_name: str) -> dict:
    """
    Parse LLM product name response into normalized parts.

    Args:
        raw_name: Raw product name from LLM

    Returns:
        Dict with 'name' (canonical), 'color' (if found), 'raw' (original)
    """
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


# Reload function for testing/development
def reload_canonical_names():
    """Force reload canonical names (clears cache)."""
    _load_canonical_names.cache_clear()
    _get_valid_product_names.cache_clear()
    logger.info("Canonical names cache cleared")
