"""
LangGraph Production Architecture.
===================================
Core modules:
- state.py: State definitions
- checkpointer.py: PostgreSQL persistence
- nodes/: Individual node modules
- edges.py: Routing logic
- graph.py: Graph assembly
- streaming.py: Real-time token streaming (UX)
- time_travel.py: State rollback/fork (debug/recovery)
"""

from .checkpointer import (
    CheckpointerType,
    get_checkpointer,
    get_postgres_checkpointer,
)
from .edges import (
    route_after_intent,
    route_after_validation,
)
from .graph import (
    build_production_graph,
    get_production_graph,
    invoke_graph,
    invoke_with_retry,
)
from .state import (
    ConversationState,
    create_initial_state,
    get_state_snapshot,
)
from .streaming import (
    StreamEventType,
    stream_events,
    stream_tokens,
)
from .time_travel import (
    fork_from_state,
    get_state_history,
    rollback_to_step,
)


__all__ = [
    # State
    "ConversationState",
    "create_initial_state",
    "get_state_snapshot",
    # Checkpointer
    "get_checkpointer",
    "get_postgres_checkpointer",
    "CheckpointerType",
    # Graph
    "build_production_graph",
    "get_production_graph",
    "invoke_graph",
    "invoke_with_retry",
    # Edges
    "route_after_intent",
    "route_after_validation",
    # Streaming (UX)
    "stream_events",
    "stream_tokens",
    "StreamEventType",
    # Time Travel (debug/recovery)
    "get_state_history",
    "rollback_to_step",
    "fork_from_state",
]
