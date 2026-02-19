"""
Base Router & Utilities.
========================
Provides the `with_state_schema` decorator and base helpers
to safely access state using Pydantic models.
"""

import logging
from typing import Any, Callable, Dict, TypeVar

from src.core.state_schema import StateSchema
from src.conf.config import settings
from src.core.state_machine import State, get_default_dialog_phase_for_state
from src.agents.langgraph.state import ConversationState

# Generic type for router functions
R = TypeVar("R")
logger = logging.getLogger(__name__)

def to_schema(state: ConversationState | Dict[str, Any]) -> StateSchema:
    """
    Safely convert TypedDict state to Pydantic StateSchema.

    This ensures we access fields safely via dot notation
    and validate types at the boundary.
    """
    # 1. Normalize to Dict
    if hasattr(state, "model_dump"):
        state_dict = state.model_dump()
    elif isinstance(state, dict):
        state_dict = state.copy()
    else:
        # Fallback for MutableMapping or other types
        state_dict = dict(state)

    # 2. Ensure Defaults (Safe Access on DICT now)
    # Router boundary sanitization only (does not weaken model globally).
    if settings.ROUTER_SCHEMA_TOLERANT:
        metadata = state_dict.get("metadata")
        metadata_dict = metadata if isinstance(metadata, dict) else {}

        session_id = (
            state_dict.get("session_id")
            or metadata_dict.get("session_id")
            or settings.DEFAULT_SESSION_ID
            or ""
        )
        state_dict["session_id"] = str(session_id)

        dialog_phase = state_dict.get("dialog_phase")
        if not isinstance(dialog_phase, str) or not dialog_phase.strip():
            raw_state = str(state_dict.get("current_state") or State.STATE_0_INIT.value)
            state_enum = State.from_string(raw_state)
            state_dict["dialog_phase"] = get_default_dialog_phase_for_state(state_enum)

    if "trace_id" not in state_dict or state_dict["trace_id"] is None:
        state_dict["trace_id"] = "" 

    if "thread_id" not in state_dict or state_dict["thread_id"] is None:
        state_dict["thread_id"] = state_dict.get("session_id", "")

    # 3. Serialize Messages (Logic preserved)
    if "messages" in state_dict and state_dict["messages"]:
        serialized_msgs = []
        for msg in state_dict["messages"]:
             if hasattr(msg, "model_dump"):
                 serialized_msgs.append(msg.model_dump())
             elif hasattr(msg, "dict"):
                  serialized_msgs.append(msg.dict())
             elif isinstance(msg, dict):
                 serialized_msgs.append(msg)
             else:
                 try:
                     serialized_msgs.append(dict(msg))
                 except (TypeError, ValueError) as serialize_error:
                     logger.debug("Router message serialization skipped: %s", serialize_error)
                     if settings.STRICT_EXCEPTION_POLICY:
                         try:
                             from src.services.observability import track_metric

                             track_metric(
                                 "fallback_triggered",
                                 1,
                                 {
                                     "fallback_reason": "router_message_serialization_error",
                                     "session_id": state_dict.get("session_id", ""),
                                     "state": state_dict.get("current_state", State.STATE_0_INIT.value),
                                     "node": "router_boundary",
                                 },
                             )
                         except Exception as metric_error:
                             logger.debug(
                                 "Router serialization metric emission failed: %s",
                                 metric_error,
                             )
        state_dict["messages"] = serialized_msgs

    # 4. Construct Schema
    return StateSchema(**state_dict)

def safe_router(func: Callable[[StateSchema], R]) -> Callable[[Dict[str, Any]], R]:
    """
    Decorator that adapts a router function expecting StateSchema
    to one that accepts a raw dict.

    Usage:
        @safe_router
        def my_router(state: StateSchema) -> str:
            if state.dialog_phase == "INIT":
                return "node_a"
            return "node_b"
    """
    def wrapper(state: Dict[str, Any]) -> R:
        schema = to_schema(state) # type: ignore
        result = func(schema)
        
        # Auto-unwrap Enums to strings for LangGraph
        if hasattr(result, "value"):
            return result.value
        return result
    return wrapper
