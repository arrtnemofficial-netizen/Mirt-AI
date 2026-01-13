"""
Routing Edges - Conditional flow control.
=========================================
This is the "glue" layer that delegates decision making to
typed routers in `src.agents.langgraph.routers`.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from src.agents.langgraph.routers.master import master_router, get_master_routes
from src.agents.langgraph.routers.intent import route_after_intent, get_intent_routes
from src.agents.langgraph.routers.post_process import (
    route_after_moderation, get_moderation_routes,
    route_after_agent, get_agent_routes,
    route_after_validation, get_validation_routes,
    route_after_vision,
    route_after_offer # Restored
)

logger = logging.getLogger(__name__)

# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "master_router", "get_master_routes",
    "route_after_intent", "get_intent_routes",
    "route_after_moderation", "get_moderation_routes",
    "route_after_agent", "get_agent_routes",
    "route_after_validation", "get_validation_routes",
    "route_after_vision",
    "route_after_offer"
]
