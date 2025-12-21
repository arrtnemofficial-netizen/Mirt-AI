"""
Memory parser configuration loader.
==================================
Loads parsing patterns and templates from Registry.
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from src.core.prompt_registry import registry

logger = logging.getLogger(__name__)


def _load_memory_parser_config() -> dict[str, Any]:
    try:
        content = registry.get("system.memory_parser").content
    except Exception as exc:
        logger.warning("Memory parser config not found: %s", exc)
        return {}

    try:
        data = yaml.safe_load(content) or {}
    except Exception as exc:
        logger.warning("Failed to parse memory parser config: %s", exc)
        return {}

    return data if isinstance(data, dict) else {}


def get_memory_parser_section(name: str) -> dict[str, Any]:
    data = _load_memory_parser_config()
    section = data.get(name, {})
    return section if isinstance(section, dict) else {}


def get_memory_template(key: str, default: str) -> str:
    templates = get_memory_parser_section("templates")
    value = templates.get(key)
    return value if isinstance(value, str) and value else default


def get_memory_label(key: str, default: str) -> str:
    labels = get_memory_parser_section("labels")
    value = labels.get(key)
    return value if isinstance(value, str) and value else default


def get_memory_patterns() -> dict[str, Any]:
    return get_memory_parser_section("patterns")
