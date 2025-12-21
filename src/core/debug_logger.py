"""Lightweight debug logger used by LangGraph nodes."""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger("mirt.debug")


def debug_log(event: str, **payload: Any) -> None:
    """Log a structured debug event."""
    try:
        logger.debug("[DEBUG] %s | %s", event, payload)
    except Exception:
        logger.debug("[DEBUG] %s", event)
