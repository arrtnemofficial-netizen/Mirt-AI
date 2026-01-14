"""
Base Router & Utilities.
========================
Provides the `with_state_schema` decorator and base helpers
to safely access state using Pydantic models.
"""

from typing import Any, Callable, TypeVar, Dict

from src.core.state_schema import StateSchema
from src.agents.langgraph.state import ConversationState

# Generic type for router functions
R = TypeVar("R")

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
                 except Exception:
                     pass 
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
