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

from src.conf.config import settings

from .checkpointer import get_checkpointer
from .edges import (
    get_agent_routes,
    get_intent_routes,
    get_master_routes,
    get_moderation_routes,
    get_validation_routes,
    master_router,
    route_after_agent,
    route_after_intent,
    route_after_moderation,
    route_after_validation,
    route_after_vision,
)
from .nodes import (
    agent_node,
    crm_error_node,
    escalation_node,
    intent_detection_node,
    memory_context_node,
    memory_update_node,
    moderation_node,
    offer_node,
    payment_node,
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

    # Create node wrappers that inject the runner
    async def _moderation(state: dict[str, Any]) -> dict[str, Any]:
        return await moderation_node(state)

    async def _intent(state: dict[str, Any]) -> dict[str, Any]:
        return await intent_detection_node(state)

    async def _vision(state: dict[str, Any]) -> dict[str, Any]:
        return await vision_node(state, runner)

    async def _agent(state: dict[str, Any]) -> dict[str, Any]:
        return await agent_node(state, runner)

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

    async def _crm_error(state: dict[str, Any]) -> dict[str, Any]:
        return await crm_error_node(state)

    async def _end(state: dict[str, Any]) -> dict[str, Any]:
        """Terminal node - just returns empty update."""
        return {"step_number": state.get("step_number", 0) + 1}

    # =========================================================================
    # MEMORY NODES (Titans-like Memory System)
    # =========================================================================
    async def _memory_context(state: dict[str, Any]) -> dict[str, Any]:
        """Load memory context before agents."""
        return await memory_context_node(state)

    async def _memory_update(state: dict[str, Any]) -> dict[str, Any]:
        """Silently update memory after key states."""
        return await memory_update_node(state)

    # Build the graph with TYPED state (enables reducers!)
    graph = StateGraph(ConversationState)

    # =========================================================================
    # ADD NODES
    # =========================================================================
    graph.add_node("moderation", _moderation)
    graph.add_node("memory_context", _memory_context)  # Memory: load before agents
    graph.add_node("intent", _intent)
    graph.add_node("vision", _vision)
    graph.add_node("agent", _agent)
    graph.add_node("offer", _offer)
    graph.add_node("payment", _payment)
    graph.add_node("upsell", _upsell)
    graph.add_node("escalation", _escalation)
    graph.add_node("validation", _validation)
    graph.add_node("crm_error", _crm_error)
    graph.add_node("memory_update", _memory_update)  # Memory: update after key states
    graph.add_node("end", _end)

    # =========================================================================
    # ENTRY POINT (Master Router for Turn-Based Conversation)
    # =========================================================================
    # Повна відповідність n8n state machine:
    #
    # dialog_phase          → node
    # ─────────────────────────────────────
    # INIT                  → moderation (повний pipeline)
    # DISCOVERY             → agent (STATE_1)
    # VISION_DONE           → agent (STATE_2→3)
    # WAITING_FOR_SIZE      → agent (STATE_3)
    # WAITING_FOR_COLOR     → agent (STATE_3)
    # SIZE_COLOR_DONE       → offer (STATE_4)
    # OFFER_MADE            → payment (STATE_5)
    # WAITING_FOR_*         → payment (STATE_5)
    # UPSELL_OFFERED        → upsell (STATE_6)
    # COMPLETED             → end (STATE_7)
    # COMPLAINT/OOD         → escalation (STATE_8/9)
    # =========================================================================
    graph.add_conditional_edges(
        START,
        master_router,
        get_master_routes(),
    )

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

    # After agent: validate or make offer
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        get_agent_routes(),
    )

    # =========================================================================
    # MEMORY EDGES (Titans-like Memory System)
    # =========================================================================
    # memory_context runs AFTER moderation, BEFORE intent
    # memory_update runs AFTER offer/upsell, BEFORE end

    graph.add_edge("memory_context", "intent")  # Memory → Intent

    # =========================================================================
    # SIMPLE EDGES
    # =========================================================================

    # Vision -> end (return multi-bubble response to user after product identification)
    graph.add_conditional_edges(
        "vision",
        route_after_vision,
        {"offer": "offer", "agent": "agent", "validation": "validation", "end": "end"},
    )

    # Agent -> memory_update -> END (capture facts from early conversation)
    graph.add_edge("agent", "memory_update")

    # Offer -> memory_update -> END (Turn-Based: wait for user confirmation)
    # Memory update runs silently after offer is made
    graph.add_edge("offer", "memory_update")

    # Payment uses Command for routing (handled internally)
    # IMPORTANT: Do NOT add static edge here!
    # payment_node returns Command(goto="end"|"upsell"|"payment") which controls routing.
    # A static edge would override Command.goto and cause step_number conflicts.
    # See: InvalidUpdateError when both payment and upsell update step_number in same tick.

    # Upsell -> memory_update -> end
    graph.add_edge("upsell", "memory_update")

    # Escalation -> end
    graph.add_edge("escalation", "end")

    # Memory update -> end (after offer/upsell)
    graph.add_edge("memory_update", "end")

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
        interrupt_before=["payment"] if settings.ENABLE_PAYMENT_HITL else [],
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
) -> CompiledGraph:
    """
    Get or create the production graph singleton.

    Args:
        runner: LLM runner (uses default if None)
        checkpointer: Persistence backend (auto-detect if None)

    Returns:
        Compiled production graph
    """
    global _production_graph

    if _production_graph is None:
        # Validate prompt files exist for all states (fail-fast)
        from src.core.prompt_registry import validate_all_states_have_prompts

        missing = validate_all_states_have_prompts()
        if missing:
            logger.warning("Graph starting with missing state prompts: %s", missing)

        try:
            from src.agents.langgraph.state_prompts import validate_payment_subphase_prompts

            missing_payment = validate_payment_subphase_prompts()
            if missing_payment:
                logger.warning("Graph starting with missing payment sub-phase prompts: %s", missing_payment)
        except Exception:
            logger.debug("Unable to validate payment sub-phase prompts", exc_info=True)

        from src.agents.pydantic.support_agent import run_support

        # Create a wrapper that matches the runner signature
        async def _default_runner(msg: str, metadata: dict[str, Any]) -> dict[str, Any]:
            from src.agents.pydantic.deps import create_deps_from_state

            deps = create_deps_from_state(metadata)
            result = await run_support(msg, deps)
            return result.model_dump()

        _production_graph = build_production_graph(
            runner or _default_runner,
            checkpointer,
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

    Args:
        state: Initial state
        session_id: Session identifier
        max_attempts: Maximum retry attempts
        graph: Graph to use

    Returns:
        Final state after execution
    """
    import asyncio

    if graph is None:
        graph = get_production_graph()

    config = {"configurable": {"thread_id": session_id}}
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            result = await graph.ainvoke(state, config=config)
            if attempt > 0:
                logger.info("Graph succeeded on attempt %d", attempt + 1)
            return result
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                wait_time = (attempt + 1) * 2  # Exponential backoff
                logger.warning(
                    "Graph invocation failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt + 1,
                    max_attempts,
                    str(e)[:100],
                    wait_time,
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    "Graph failed after %d attempts: %s",
                    max_attempts,
                    str(e),
                )

    # All attempts failed - return error state
    return {
        **state,
        "should_escalate": True,
        "escalation_reason": f"System error after {max_attempts} attempts: {last_error}",
        "last_error": str(last_error),
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
