"""
Client parser configuration loader.
==================================
Loads parsing patterns and vocabularies from Registry.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import yaml

from src.core.prompt_registry import registry

logger = logging.getLogger(__name__)

_CACHE: dict[str, Any] | None = None


def _load_client_parser_config() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    try:
        content = registry.get("system.client_parser").content
    except Exception as exc:
        logger.warning("Client parser config not found: %s", exc)
        _CACHE = {}
        return _CACHE

    try:
        data = yaml.safe_load(content) or {}
    except Exception as exc:
        logger.warning("Failed to parse client parser config: %s", exc)
        _CACHE = {}
        return _CACHE

    _CACHE = data if isinstance(data, dict) else {}
    return _CACHE


def _validate_regex_pattern(pattern: str, pattern_name: str, pattern_index: int | None = None) -> bool:
    """Validate a regex pattern and log warnings if invalid.
    
    Args:
        pattern: The regex pattern string to validate
        pattern_name: Name/description of the pattern (for logging)
        pattern_index: Optional index in list (for logging)
        
    Returns:
        True if pattern is valid, False otherwise
    """
    if not pattern or not isinstance(pattern, str):
        return False
        
    try:
        # Try to compile the pattern
        re.compile(pattern)
        return True
    except re.error as e:
        idx_str = f"[{pattern_index}]" if pattern_index is not None else ""
        logger.warning(
            "Invalid regex pattern %s %s (length=%d, error=%s, error_pos=%s): %.100s",
            pattern_name,
            idx_str,
            len(pattern),
            str(e),
            getattr(e, "pos", "unknown"),
            pattern[:100] if len(pattern) > 100 else pattern,
        )
        return False


def get_client_parser_list(key: str) -> list[str]:
    data = _load_client_parser_config()
    value = data.get(key, [])
    if isinstance(value, list):
        validated_patterns = []
        for idx, item in enumerate(value):
            if not item:
                continue
            pattern_str = str(item)
            # Validate regex patterns (only for pattern keys, not simple lists like cities)
            if key.endswith("_patterns") and not _validate_regex_pattern(pattern_str, f"{key}[{idx}]", idx):
                continue  # Skip invalid patterns
            validated_patterns.append(pattern_str)
        return validated_patterns
    return []


def get_client_parser_value(key: str, default: str) -> str:
    data = _load_client_parser_config()
    value = data.get(key)
    if isinstance(value, str) and value:
        # Validate regex patterns if the key suggests it's a pattern
        if key.endswith("_pattern") or key.endswith("_patterns"):
            if not _validate_regex_pattern(value, key):
                logger.warning("Using default pattern for %s due to validation failure", key)
                return default
        return value
    return default
