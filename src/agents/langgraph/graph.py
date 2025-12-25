"""
Production Graph Builder.
==========================
This is where everything comes together.

Architecture:
- Checkpointer for persistence (PostgreSQL)
- Conditional edges for smart routing
- Self-correction loops (validation -> retry)
- Human-in-the-loop for payments (interrupt)
- Proper error handling

This graph is designed to SURVIVE in production.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph

from .checkpointer import get_checkpointer
from .edges import (
    get_agent_routes,
    get_intent_routes,
    get_moderation_routes,
    get_validation_routes,
    route_after_agent,
    route_after_intent,
    route_after_moderation,
    route_after_validation,
    route_after_vision,
)
from .nodes import (
    agent_node,
    escalation_node,
    intent_detection_node,
    moderation_node,
    offer_node,
    payment_node,
    sitniks_status,
    upsell_node,
    validation_node,
    vision_node,
)
from .state import ConversationState, create_initial_state


if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.graph import CompiledGraph

# Type alias for runner function
RunnerFunc = Callable[[str, dict[str, Any]], dict[str, Any]]

logger = logging.getLogger(__name__)


# =============================================================================
# GRAPH BUILDER
# =============================================================================


def build_production_graph(
    runner: RunnerFunc,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledGraph:
    """
    Build the production-ready graph.

    This graph has:
    1. Moderation gate (first line of defense)
    2. Intent detection (smart routing)
    3. Specialized nodes (vision, agent, offer, payment)
    4. Validation with self-correction loops
    5. Human-in-the-loop for payments
    6. Proper escalation handling

    Args:
        runner: LLM runner function (from pydantic_agent)
        checkpointer: State persistence backend (auto-detect if None)

    Returns:
        Compiled graph ready for production
    """
    logger.info("Building production graph...")

    # SAFEGUARD: Verify sitniks_status is callable (not an object with method)
    if not callable(sitniks_status):
        raise ValueError(
            f"sitniks_status must be callable, got: {type(sitniks_status).__name__}. "
            "Check imports in src/agents/langgraph/nodes/__init__.py"
        )

    # Create node wrappers that inject the runner
    async def _moderation(state: dict[str, Any]) -> dict[str, Any]:
        return await moderation_node(state)

    async def _intent(state: dict[str, Any]) -> dict[str, Any]:
        return await intent_detection_node(state)

    async def _vision(state: dict[str, Any]) -> dict[str, Any]:
        return await vision_node(state, runner)

    async def _agent(state: dict[str, Any]) -> dict[str, Any]:
        return await agent_node(state, runner)

    async def _sitniks_status(state: dict[str, Any]) -> dict[str, Any]:
        # SAFEGUARD: Double-check at runtime (defense in depth)
        if not callable(sitniks_status):
            logger.error(
                "sitniks_status is not callable at runtime! Type: %s, Value: %s",
                type(sitniks_status).__name__,
                sitniks_status,
            )
            return {"step_number": state.get("step_number", 0) + 1}
        # update_sitniks_status is synchronous, returns dict directly
        return sitniks_status(state)

    async def _offer(state: dict[str, Any]) -> dict[str, Any]:
        return await offer_node(state, runner)

    async def _payment(state: dict[str, Any]) -> dict[str, Any]:
        return await payment_node(state, runner)

    async def _upsell(state: dict[str, Any]) -> dict[str, Any]:
        return await upsell_node(state, runner)

    async def _escalation(state: dict[str, Any]) -> dict[str, Any]:
        return await escalation_node(state)

    async def _validation(state: dict[str, Any]) -> dict[str, Any]:
        return await validation_node(state)

    async def _end(state: dict[str, Any]) -> dict[str, Any]:
        """Terminal node - just returns empty update."""
        return {"step_number": state.get("step_number", 0) + 1}

    # Build the graph with TYPED state (enables reducers!)
    graph = StateGraph(ConversationState)

    # =========================================================================
    # ADD NODES
    # =========================================================================
    graph.add_node("moderation", _moderation)
    graph.add_node("intent", _intent)
    graph.add_node("vision", _vision)
    graph.add_node("agent", _agent)
    graph.add_node("sitniks_status", _sitniks_status)
    graph.add_node("offer", _offer)
    graph.add_node("payment", _payment)
    graph.add_node("upsell", _upsell)
    graph.add_node("escalation", _escalation)
    graph.add_node("validation", _validation)
    graph.add_node("end", _end)

    # =========================================================================
    # ENTRY POINT
    # =========================================================================
    graph.add_edge(START, "moderation")

    # =========================================================================
    # CONDITIONAL EDGES (Smart Routing)
    # =========================================================================

    # After moderation: intent detection or escalation
    graph.add_conditional_edges(
        "moderation",
        route_after_moderation,
        get_moderation_routes(),
    )

    # After intent: route to appropriate handler
    graph.add_conditional_edges(
        "intent",
        route_after_intent,
        get_intent_routes(),
    )

    # After validation: retry, escalate, or proceed
    # THIS IS THE SELF-CORRECTION LOOP
    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        get_validation_routes(),
    )

    # After agent: update Sitniks status, then route
    graph.add_edge("agent", "sitniks_status")
    
    # After sitniks_status: validate or make offer
    graph.add_conditional_edges(
        "sitniks_status",
        route_after_agent,
        get_agent_routes(),
    )

    # =========================================================================
    # SIMPLE EDGES
    # =========================================================================

    # Vision -> offer/escalation/agent/validation (based on result)
    graph.add_conditional_edges(
        "vision",
        route_after_vision,
        {"offer": "offer", "agent": "agent", "validation": "validation", "escalation": "escalation"},
    )

    # Offer -> validation (check before sending)
    graph.add_edge("offer", "validation")

    # Payment uses Command for routing (handled internally)
    # But we need edges for the graph structure
    graph.add_edge("payment", "upsell")  # Default path

    # Upsell -> end
    graph.add_edge("upsell", "end")

    # Escalation -> end
    graph.add_edge("escalation", "end")

    # End -> END
    graph.add_edge("end", END)

    # =========================================================================
    # COMPILE WITH CHECKPOINTER + INTERRUPT
    # =========================================================================
    if checkpointer is None:
        checkpointer = get_checkpointer()

    # CRITICAL: interrupt_before enables Human-in-the-Loop
    # Without this, the graph won't pause before payment!
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["payment"],  # HITL: pause before payment node
    )
    logger.info("Production graph built with HITL interrupt_before=['payment']")

    return compiled


# =============================================================================
# SINGLETON MANAGEMENT
# =============================================================================

_production_graph: CompiledGraph | None = None


def get_production_graph(
    runner: RunnerFunc | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    force_rebuild: bool = False,
) -> CompiledGraph:
    """
    Get or create the production graph singleton.

    Args:
        runner: LLM runner (uses default if None)
        checkpointer: Persistence backend (auto-detect if None)
        force_rebuild: Force rebuild of graph even if cached (useful after code changes)

    Returns:
        Compiled production graph
    """
    global _production_graph

    if force_rebuild:
        logger.info("Force rebuilding production graph (force_rebuild=True)")
        _production_graph = None

    if _production_graph is None:
        if runner is None:
            from src.agents.pydantic.main_agent import run_main

            # Create a wrapper that matches the runner signature
            async def _default_runner(msg: str, metadata: dict[str, Any]) -> dict[str, Any]:
                from src.agents.pydantic.deps import create_deps_from_state

                deps = create_deps_from_state(metadata)
                result = await run_main(msg, deps)
                return result.model_dump()

            runner = _default_runner

        _production_graph = build_production_graph(
            runner,
            checkpointer,
        )
        
        # Assert that graph was created successfully
        if _production_graph is None:
            raise RuntimeError(
                "build_production_graph returned None. "
                "This indicates a critical error in graph initialization."
            )

    # Additional safety check (should never happen if build_production_graph works correctly)
    if _production_graph is None:
        raise RuntimeError(
            "_production_graph is None after initialization. "
            "This should never happen. Check build_production_graph implementation."
        )

    return _production_graph


def reset_graph() -> None:
    """Reset the graph singleton (useful for testing)."""
    global _production_graph
    _production_graph = None


# =============================================================================
# INVOCATION HELPERS
# =============================================================================


async def invoke_graph(
    state: dict[str, Any] | None = None,
    session_id: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    graph: CompiledGraph | None = None,
) -> dict[str, Any]:
    """
    Invoke the graph with proper thread_id for persistence.

    Args:
        state: Full state dict (or build from components below)
        session_id: Session identifier (becomes thread_id)
        messages: Message history (if not providing state)
        metadata: Additional metadata (if not providing state)
        graph: Graph to use (default: production graph)

    Returns:
        Updated state after graph execution
    """
    # Get or create graph
    if graph is None:
        graph = get_production_graph()

    # Build state if not provided
    if state is None:
        if session_id is None:
            raise ValueError("Either state or session_id must be provided")
        state = create_initial_state(
            session_id=session_id,
            messages=messages,
            metadata=metadata,
        )
    else:
        session_id = state.get("session_id", state.get("metadata", {}).get("session_id"))

    if not session_id:
        raise ValueError("session_id is required for graph invocation")

    # Thread ID for checkpointer
    config = {"configurable": {"thread_id": session_id}}

    # Invoke
    return await graph.ainvoke(state, config=config)


async def invoke_with_retry(
    state: dict[str, Any],
    session_id: str,
    max_attempts: int = 3,
    graph: CompiledGraph | None = None,
) -> dict[str, Any]:
    """
    Invoke graph with external retry logic.

    This is a fallback for catastrophic failures that the graph
    can't handle internally (e.g., network issues).

    SAFEGUARDS:
    - Blacklist for unsafe operations (payment, order creation)
    - Detailed logging (error_type, error_message, attempt_number, node_name)
    - Max delay cap (30s)

    Args:
        state: Initial state
        session_id: Session identifier
        max_attempts: Maximum retry attempts
        graph: Graph to use

    Returns:
        Final state after execution
    """
    import asyncio

    # SAFEGUARD_1: Blacklist for unsafe operations
    UNSAFE_NODES = {"payment", "order_creation", "create_order"}
    current_state = state.get("current_state", "")
    current_node = state.get("current_node", "")
    
    # Check if we're in an unsafe node
    is_unsafe = (
        any(unsafe in current_state.lower() for unsafe in UNSAFE_NODES)
        or any(unsafe in current_node.lower() for unsafe in UNSAFE_NODES)
        or state.get("dialog_phase") == "payment"
    )
    
    if is_unsafe:
        logger.warning(
            "[RETRY] Blacklisted: unsafe operation detected (state=%s, node=%s). No retry for payment/order operations.",
            current_state,
            current_node,
        )
        # For unsafe operations, invoke once without retry
        if graph is None:
            graph = get_production_graph()
        config = {"configurable": {"thread_id": session_id}}
        try:
            return await graph.ainvoke(state, config=config)
        except Exception as e:
            logger.error(
                "[RETRY] Unsafe operation failed (no retry): error_type=%s error_message=%s",
                type(e).__name__,
                str(e)[:200],
            )
            return {
                **state,
                "should_escalate": True,
                "escalation_reason": f"Unsafe operation failed (no retry): {type(e).__name__}",
                "last_error": str(e),
            }

    if graph is None:
        graph = get_production_graph()

    config = {"configurable": {"thread_id": session_id}}
    last_error: Exception | None = None
    max_delay_cap = 30  # SAFEGUARD_3: Max delay cap (30s)

    for attempt in range(max_attempts):
        try:
            result = await graph.ainvoke(state, config=config)
            if attempt > 0:
                logger.info(
                    "[RETRY] Graph succeeded on attempt %d/%d for session=%s",
                    attempt + 1,
                    max_attempts,
                    session_id,
                )
            return result
        except Exception as e:
            last_error = e
            error_type = type(e).__name__
            error_message = str(e)[:200]
            node_name = current_node or state.get("current_node", "unknown")
            
            if attempt < max_attempts - 1:
                # SAFEGUARD_3: Max delay cap
                wait_time = min((attempt + 1) * 2, max_delay_cap)  # Exponential backoff with cap
                
                # SAFEGUARD_2: Detailed logging
                logger.warning(
                    "[RETRY] Graph invocation failed: attempt=%d/%d session=%s error_type=%s error_message=%s node_name=%s retry_delay=%ds",
                    attempt + 1,
                    max_attempts,
                    session_id,
                    error_type,
                    error_message,
                    node_name,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
            else:
                # SAFEGUARD_2: Detailed logging for final failure
                logger.error(
                    "[RETRY] Graph failed after %d attempts: session=%s error_type=%s error_message=%s node_name=%s",
                    max_attempts,
                    session_id,
                    error_type,
                    error_message,
                    node_name,
                )

    # All attempts failed - return error state
    return {
        **state,
        "should_escalate": True,
        "escalation_reason": f"System error after {max_attempts} attempts: {type(last_error).__name__ if last_error else 'Unknown'}",
        "last_error": str(last_error) if last_error else "Unknown error",
    }


async def resume_after_interrupt(
    session_id: str,
    response: Any,
    graph: CompiledGraph | None = None,
) -> dict[str, Any]:
    """
    Resume graph after human-in-the-loop interrupt.

    Used for payment confirmations and other approval flows.

    Args:
        session_id: Session to resume
        response: Human's response (True/False for approval)
        graph: Graph to use

    Returns:
        Updated state after resumption
    """
    from langgraph.types import Command

    if graph is None:
        graph = get_production_graph()

    config = {"configurable": {"thread_id": session_id}}

    logger.info("Resuming graph for session %s with response: %s", session_id, response)

    return await graph.ainvoke(Command(resume=response), config=config)
