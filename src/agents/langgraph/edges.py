"""
Routing Edges - Conditional flow control.
=========================================
This is the "glue" layer that delegates decision making to
typed routers in `src.agents.langgraph.routers`.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.langgraph.routers.master import master_router, get_master_routes
from src.agents.langgraph.routers.intent import route_after_intent, get_intent_routes
from src.agents.langgraph.routers.post_process import (
    route_after_moderation, get_moderation_routes,
    route_after_agent, get_agent_routes,
    route_after_validation, get_validation_routes,
    route_after_vision, get_vision_routes,
    route_after_offer # Restored
)

logger = logging.getLogger(__name__)

# =============================================================================
# EXPORTS
# =============================================================================


def _resolve_intent_route(intent: str, current_state: str, state: dict[str, Any]) -> str:
    """Compatibility helper for tests/tools that resolve route by intent + state snapshot."""
    normalized_intent = str(intent or "")
    has_image = bool(state.get("has_image", False))
    if normalized_intent == "PHOTO_IDENT":
        # Compatibility: PHOTO_IDENT is produced only for image turns, so emulate that signal
        # for state-less invariant tests calling this helper directly.
        has_image = True

    payload = {
        **state,
        "detected_intent": normalized_intent,
        "current_state": current_state,
        "has_image": has_image,
    }
    return route_after_intent(payload)

__all__ = [
    "master_router", "get_master_routes",
    "_resolve_intent_route",
    "route_after_intent", "get_intent_routes",
    "route_after_moderation", "get_moderation_routes",
    "route_after_agent", "get_agent_routes",
    "route_after_validation", "get_validation_routes",
    "route_after_vision", "get_vision_routes",
    "route_after_offer"
]
