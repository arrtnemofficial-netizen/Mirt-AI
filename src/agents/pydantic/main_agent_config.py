"""
Main agent configuration loader.
===============================
Loads templates and labels from Registry.
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from src.core.prompt_registry import registry

logger = logging.getLogger(__name__)

_CACHE: dict[str, Any] | None = None


def _load_main_agent_config() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    try:
        content = registry.get("system.main_agent").content
    except Exception as exc:
        logger.warning("Main agent config not found: %s", exc)
        _CACHE = {}
        return _CACHE

    try:
        data = yaml.safe_load(content) or {}
    except Exception as exc:
        logger.warning("Failed to parse main agent config: %s", exc)
        _CACHE = {}
        return _CACHE

    _CACHE = data if isinstance(data, dict) else {}
    return _CACHE


def get_main_agent_section(name: str) -> dict[str, Any]:
    data = _load_main_agent_config()
    section = data.get(name, {})
    return section if isinstance(section, dict) else {}


def get_main_agent_value(section: str, key: str, default: str) -> str:
    data = get_main_agent_section(section)
    value = data.get(key)
    return value if isinstance(value, str) and value else default


def get_main_agent_mapping(section: str) -> dict[str, str]:
    data = get_main_agent_section(section)
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items() if v}
    return {}
