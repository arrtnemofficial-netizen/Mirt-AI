"""
Intent Router.
==============
Routing logic after intent detection.
"""

from typing import Dict, Literal

from src.agents.langgraph.routers.base import safe_router, StateSchema
from src.agents.langgraph.routers.enums import Route
from src.core.state_machine import Intent, map_state_to_router_node, resolve_next_state


def get_intent_routes() -> Dict[str, str]:
    return {
        Route.VISION.value: "vision",
        Route.AGENT.value: "agent",
        Route.OFFER.value: "offer",
        Route.PAYMENT.value: "payment",
        Route.ESCALATION.value: "escalation",
        Route.DISAMBIGUATION.value: "agent",
        Route.END.value: "end",
    }


@safe_router
def route_after_intent(
    state: StateSchema,
) -> Literal["vision", "agent", "offer", "payment", "escalation", "end"]:
    """Map SSOT transition decision to a graph node route."""
    intent_value = str(state.detected_intent or "UNKNOWN_OR_EMPTY")

    if intent_value == "AMBIGUOUS":
        return Route.DISAMBIGUATION

    current_state = state.state_enum
    intent = Intent.from_string(intent_value)
    next_state = resolve_next_state(current_state, intent)
    route = map_state_to_router_node(next_state)
    return Route(route)
