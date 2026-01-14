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

def to_schema(state: ConversationState) -> StateSchema:
    """
    Safely convert TypedDict state to Pydantic StateSchema.

    This ensures we access fields safely via dot notation
    and validate types at the boundary.
    """
    # Ensure required fields exist.
    # In tests, create_initial_state sets trace_id, but if state is modified manually
    # or passed as a partial dict, it might be missing.
    if "trace_id" not in state or state["trace_id"] is None:
        state["trace_id"] = "" # Default to empty string if missing/None

    if "thread_id" not in state or state["thread_id"] is None:
        # thread_id usually matches session_id
        state["thread_id"] = state.get("session_id", "")

    # Filter out keys that might not be in StateSchema yet
    # (since allow_extra is True in Schema, this is safe, but explicit is better)
    
    # CRITICAL FIX: Serialize messages to dicts if they are LangChain objects
    # StateSchema expects List[Dict], but LangGraph may pass List[BaseMessage]
    state_copy = state.copy()
    if "messages" in state_copy and state_copy["messages"]:
        serialized_msgs = []
        for msg in state_copy["messages"]:
             if hasattr(msg, "model_dump"):
                 serialized_msgs.append(msg.model_dump())
             elif hasattr(msg, "dict"):
                  serialized_msgs.append(msg.dict())
             elif isinstance(msg, dict):
                 serialized_msgs.append(msg)
             else:
                 # Fallback for unknown types
                 try:
                     serialized_msgs.append(dict(msg))
                 except Exception:
                     pass # Skip uncleanable messages
        state_copy["messages"] = serialized_msgs

    return StateSchema(**state_copy)

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
