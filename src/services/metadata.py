"""Shared metadata helpers for agent orchestration."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.conf.config import settings
from src.core.constants import AgentState as StateEnum, EscalationLevel


def apply_metadata_defaults(metadata: Optional[Dict[str, Any]], current_state: str) -> Dict[str, Any]:
    """Populate mandatory metadata fields with safe defaults.

    The LLM prompt expects these keys to always be present. This helper keeps
    the behaviour consistent between runtime invocation and moderation
    short-circuits.
    """

    base = {
        "session_id": settings.DEFAULT_SESSION_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "current_state": current_state or StateEnum.default(),
        "event_trigger": "",
        "escalation_level": EscalationLevel.NONE,
        "notes": "",
        "moderation_flags": [],
    }
    if metadata:
        base.update(metadata)
    return base
