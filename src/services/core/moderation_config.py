"""
Moderation configuration loader.
===============================
Loads forbidden terms and substitution map from Registry.
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from src.core.prompt_registry import registry

logger = logging.getLogger(__name__)

_CACHE: dict[str, Any] | None = None


def _load_moderation_config() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    try:
        content = registry.get("system.moderation").content
    except Exception as exc:
        logger.warning("Moderation config not found: %s", exc)
        _CACHE = {}
        return _CACHE

    try:
        data = yaml.safe_load(content) or {}
    except Exception as exc:
        logger.warning("Failed to parse moderation config: %s", exc)
        _CACHE = {}
        return _CACHE

    _CACHE = data if isinstance(data, dict) else {}
    return _CACHE


def get_forbidden_terms() -> set[str]:
    data = _load_moderation_config()
    terms = data.get("forbidden_terms", [])
    if isinstance(terms, list):
        return {str(term) for term in terms if term}
    return set()


def get_substitution_map() -> dict[str, str]:
    data = _load_moderation_config()
    value = data.get("substitution_map", {})
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items() if k}
    return {}
