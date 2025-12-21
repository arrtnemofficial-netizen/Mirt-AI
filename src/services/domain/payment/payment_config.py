"""
Payment configuration loader.
=============================
Loads payment-related templates, labels, and keywords from Registry.
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from src.core.prompt_registry import registry

logger = logging.getLogger(__name__)


def _load_payment_config() -> dict[str, Any]:
    try:
        content = registry.get("system.payment_context").content
    except Exception as exc:
        logger.warning("Payment config not found: %s", exc)
        return {}

    try:
        data = yaml.safe_load(content) or {}
    except Exception as exc:
        logger.warning("Failed to parse payment config: %s", exc)
        return {}

    return data if isinstance(data, dict) else {}


def get_payment_section(name: str) -> dict[str, Any]:
    data = _load_payment_config()
    section = data.get(name, {})
    return section if isinstance(section, dict) else {}


def get_payment_value(section: str, key: str, default: str) -> str:
    data = get_payment_section(section)
    value = data.get(key)
    return value if isinstance(value, str) and value else default


def get_payment_list(section: str, key: str) -> list[str]:
    data = get_payment_section(section)
    value = data.get(key, [])
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []
