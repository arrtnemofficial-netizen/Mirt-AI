"""
MIRT AI Agents - Production Architecture.
=========================================
PydanticAI + LangGraph integration.

Structure:
- pydantic/    <- Agent logic (THE BRAIN)
- langgraph/   <- Orchestration (THE CONDUCTOR)

Quick Start:
    from src.agents import run_support, AgentDeps, get_active_graph

    # 1. Run agent directly
    deps = AgentDeps(session_id="123", current_state="STATE_0_INIT")
    response = await run_support("Привіт!", deps)

    # 2. Run via LangGraph
    graph = get_active_graph()
    result = await graph.ainvoke(state, config={"configurable": {"thread_id": "123"}})
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from langgraph.graph.graph import CompiledGraph

# =============================================================================
# PYDANTIC AI AGENTS (The Brain)
# =============================================================================

# =============================================================================
# LANGGRAPH ORCHESTRATION (The Conductor)
# =============================================================================
from .langgraph import (
    CheckpointerType,
    # State
    ConversationState,
    StreamEventType,
    # Graph
    build_production_graph,
    create_initial_state,
    fork_from_state,
    # Checkpointer (Persistence!)
    get_checkpointer,
    get_postgres_checkpointer,
    get_production_graph,
    # Time Travel (debug/recovery)
    get_state_history,
    get_state_snapshot,
    invoke_graph,
    invoke_with_retry,
    rollback_to_step,
    # Routing
    route_after_intent,
    route_after_validation,
    # Streaming (UX)
    stream_events,
    stream_tokens,
)
from .pydantic import (
    # Dependencies (DI container)
    AgentDeps,
    EventType,
    # Type literals
    IntentType,
    MessageItem,
    PaymentResponse,
    ProductMatch,
    ResponseMetadata,
    StateType,
    # Output models (OUTPUT_CONTRACT)
    SupportResponse,
    VisionResponse,
    create_deps_from_state,
    get_payment_agent,
    # Agent factories (for advanced use)
    get_support_agent,
    get_vision_agent,
    run_payment,
    # Agent runners (what you call)
    run_support,
    run_vision,
)

# Observability
from .pydantic.observability import setup_observability


# =============================================================================
# MAIN ENTRY POINTS
# =============================================================================


def get_active_graph() -> CompiledGraph:
    """
    Get production-ready LangGraph.

    Features:
    - PostgreSQL persistence (survives restarts)
    - Human-in-the-loop for payments
    - Self-correction loops
    - Streaming support
    """
    return get_production_graph()


# Alias
AgentState = ConversationState


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Entry points
    "get_active_graph",
    "setup_observability",
    # PydanticAI
    "AgentDeps",
    "create_deps_from_state",
    "SupportResponse",
    "VisionResponse",
    "PaymentResponse",
    "ProductMatch",
    "MessageItem",
    "ResponseMetadata",
    "IntentType",
    "StateType",
    "EventType",
    "run_support",
    "run_vision",
    "run_payment",
    "get_support_agent",
    "get_vision_agent",
    "get_payment_agent",
    # LangGraph
    "ConversationState",
    "AgentState",
    "create_initial_state",
    "get_state_snapshot",
    "get_checkpointer",
    "get_postgres_checkpointer",
    "CheckpointerType",
    "build_production_graph",
    "get_production_graph",
    "invoke_graph",
    "invoke_with_retry",
    "route_after_intent",
    "route_after_validation",
    # Streaming (UX) - future feature
    "stream_events",
    "stream_tokens",
    "StreamEventType",
    # Time Travel (debug/recovery) - future feature
    "get_state_history",
    "rollback_to_step",
    "fork_from_state",
]
