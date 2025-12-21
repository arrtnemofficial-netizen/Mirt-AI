"""
Client parser configuration loader.
==================================
Loads parsing patterns and vocabularies from Registry.
"""

from __future__ import annotations

import logging
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


def get_client_parser_list(key: str) -> list[str]:
    data = _load_client_parser_config()
    value = data.get(key, [])
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def get_client_parser_value(key: str, default: str) -> str:
    data = _load_client_parser_config()
    value = data.get(key)
    return value if isinstance(value, str) and value else default
