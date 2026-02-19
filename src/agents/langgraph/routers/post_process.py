"""
Post-Processing Routers.
========================
Routers for agent, moderation, validation, vision steps.
"""

from typing import Dict, Literal, Any
from src.core.state_machine import State
from src.agents.langgraph.routers.base import safe_router, StateSchema


# --- Moderation ---

def get_moderation_routes() -> Dict[str, str]:
    return {
        "intent": "memory_context", # Go through memory context first
        "escalation": "escalation"
    }

@safe_router
def route_after_moderation(state: StateSchema) -> Literal["intent", "escalation"]:
    # Check strict moderation result first
    if state.moderation_result and state.moderation_result.get("allowed") is False:
        return "escalation"

    if state.should_escalate:
        return "escalation"
    return "intent"


# --- Agent ---

def get_agent_routes() -> Dict[str, str]:
    return {
        "offer": "offer",
        "validation": "validation",
        "payment": "payment", # Shortcut for direct buy
        "end": "end",
        "escalation": "escalation",
        "post_agent_memory": "memory_update",
    }

@safe_router
def route_after_agent(
    state: StateSchema,
) -> Literal["offer", "validation", "payment", "end", "escalation", "post_agent_memory"]:
    """
    Agent has produced a response. Where to next?
    """
    agent_error = state.agent_response.get("agent_error") if isinstance(state.agent_response, dict) else None
    if isinstance(agent_error, dict):
        recoverable = bool(agent_error.get("recoverable", False))
        return "validation" if recoverable else "escalation"

    # Turn-Based Check: if agent set a waiting phase, run memory post-hook then end
    waiting_phases = {
        "DISCOVERY", "VISION_DONE", "WAITING_FOR_SIZE", "WAITING_FOR_COLOR",
        "OFFER_MADE", "WAITING_FOR_DELIVERY_DATA", "WAITING_FOR_PAYMENT_METHOD",
        "WAITING_FOR_PAYMENT_PROOF", "UPSELL_OFFERED", "COMPLETED", "ESCALATED"
    }
    if state.dialog_phase in waiting_phases:
        return "post_agent_memory"

    # If agent prepared an offer (Structured Output), go to Offer node to render it
    if state.dialog_phase == "SIZE_COLOR_DONE":
        return "offer"

    if state.state_enum == State.STATE_4_OFFER:
        return "offer"

    # If agent detected payment intent mid-dialog
    if state.state_enum == State.STATE_5_PAYMENT_DELIVERY:
        return "payment"

    # Default: Validate the agent's response (Self-Correction)
    return "validation"


# --- Offer ---

def route_after_offer(state: Dict[str, Any]) -> Literal["payment", "validation"]:
    """
    Route after offer presented.
    Note: Offer node typically ends turn, but if it doesn't...
    Using legacy dict access here or we can wrap it.
    """
    # Original implementation:
    # intent = state.get("detected_intent", "")
    # if intent == "PAYMENT_DELIVERY": return "payment"
    # return "validation"

    # Let's use our safe wrapper pattern to keep it consistent
    return _route_after_offer_safe(state)

@safe_router
def _route_after_offer_safe(state: StateSchema) -> Literal["payment", "validation"]:
    if state.detected_intent == "PAYMENT_DELIVERY":
        return "payment"
    return "validation"


# --- Validation ---

def get_validation_routes() -> Dict[str, str]:
    return {
        "agent": "agent",   # Retry
        "offer": "offer",   # Proceed (late offer detection)
        "end": "end",       # Success -> User
        "escalation": "escalation" # Give up
    }

@safe_router
def route_after_validation(state: StateSchema) -> Literal["agent", "offer", "end", "escalation"]:
    if state.validation_errors:
        if state.retry_count > state.max_retries:
            return "escalation"
        return "agent" # Retry generation

    # Late offer detection check?
    if state.state_enum == State.STATE_4_OFFER:
        return "offer"

    return "end"


# --- Vision ---

@safe_router
def route_after_vision(state: StateSchema) -> Literal["offer", "agent", "validation", "end"]:
    """
    After vision analysis.
    """
    # Error -> validate
    if state.last_error:
        return "validation"

    # Always end after vision to deliver vision-built messages to the user.
    return "end"
