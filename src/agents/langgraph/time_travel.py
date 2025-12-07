"""
Time Travel - State rollback and forking.
==========================================
When things go wrong, go back in time.

Use cases:
- Customer: "Ні, я передумав, давай повернемось до вибору кольору"
- Support: "Ой, клієнт натиснув не ту кнопку"
- Debug: "Що сталося на кроці 5?"

This is a KILLER FEATURE for support teams.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from langgraph.graph.graph import CompiledGraph

logger = logging.getLogger(__name__)


async def get_state_history(
    graph: CompiledGraph,
    session_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Get history of state snapshots for a session.

    Each entry contains:
    - checkpoint_id: Unique ID for this state
    - step: Step number in the graph
    - state: The full state at that point
    - timestamp: When this state was saved
    - node: Which node produced this state

    Args:
        graph: Compiled graph with checkpointer
        session_id: Session to get history for
        limit: Maximum number of snapshots to return

    Returns:
        List of state snapshots, newest first
    """
    config = {"configurable": {"thread_id": session_id}}

    try:
        # Get state history from checkpointer
        history = []
        async for state_snapshot in graph.aget_state_history(config, limit=limit):
            history.append(
                {
                    "checkpoint_id": state_snapshot.config.get("configurable", {}).get(
                        "checkpoint_id"
                    ),
                    "step": state_snapshot.values.get("step_number", 0),
                    "current_state": state_snapshot.values.get("current_state"),
                    "detected_intent": state_snapshot.values.get("detected_intent"),
                    "products_count": len(state_snapshot.values.get("selected_products", [])),
                    "has_error": bool(state_snapshot.values.get("last_error")),
                    "timestamp": state_snapshot.created_at,
                    "next_node": state_snapshot.next,
                    # Include full values for debugging
                    "_values": state_snapshot.values,
                }
            )

        return history

    except Exception as e:
        logger.error("Failed to get state history for %s: %s", session_id, e)
        return []


async def get_state_at_checkpoint(
    graph: CompiledGraph,
    session_id: str,
    checkpoint_id: str,
) -> dict[str, Any] | None:
    """
    Get the full state at a specific checkpoint.

    Args:
        graph: Compiled graph
        session_id: Session identifier
        checkpoint_id: Checkpoint to retrieve

    Returns:
        State dict at that checkpoint, or None if not found
    """
    config = {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_id": checkpoint_id,
        }
    }

    try:
        state_snapshot = await graph.aget_state(config)
        if state_snapshot:
            return state_snapshot.values
        return None
    except Exception as e:
        logger.error("Failed to get state at checkpoint %s: %s", checkpoint_id, e)
        return None


async def rollback_to_step(
    graph: CompiledGraph,
    session_id: str,
    target_step: int,
) -> dict[str, Any] | None:
    """
    Rollback to a specific step number.

    This finds the checkpoint at that step and returns the state.
    Use with `fork_from_state` to continue from there.

    Args:
        graph: Compiled graph
        session_id: Session identifier
        target_step: Step number to rollback to

    Returns:
        State at that step, or None if not found
    """
    config = {"configurable": {"thread_id": session_id}}

    try:
        async for state_snapshot in graph.aget_state_history(config):
            step = state_snapshot.values.get("step_number", 0)
            if step == target_step:
                logger.info(
                    "Found state at step %d for session %s",
                    target_step,
                    session_id,
                )
                return state_snapshot.values

        logger.warning("Step %d not found for session %s", target_step, session_id)
        return None

    except Exception as e:
        logger.error("Failed to rollback to step %d: %s", target_step, e)
        return None


async def fork_from_state(
    graph: CompiledGraph,
    source_session_id: str,
    new_session_id: str,
    checkpoint_id: str | None = None,
    modifications: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Create a new conversation branch from an existing state.

    This is powerful for:
    - "Let me try a different approach with this customer"
    - "Undo that last action and go a different way"
    - A/B testing different conversation paths

    Args:
        graph: Compiled graph
        source_session_id: Original session to fork from
        new_session_id: New session ID for the fork
        checkpoint_id: Specific checkpoint to fork from (latest if None)
        modifications: Changes to apply to the forked state

    Returns:
        The forked state in the new session
    """
    # Get source state
    source_config = {"configurable": {"thread_id": source_session_id}}
    if checkpoint_id:
        source_config["configurable"]["checkpoint_id"] = checkpoint_id

    try:
        source_state = await graph.aget_state(source_config)
        if not source_state:
            logger.error("Source state not found for session %s", source_session_id)
            return None

        # Create forked state
        forked_values = dict(source_state.values)

        # Update identifiers
        forked_values["session_id"] = new_session_id
        forked_values["thread_id"] = new_session_id
        forked_values["parent_checkpoint_id"] = checkpoint_id
        if "metadata" in forked_values:
            forked_values["metadata"]["session_id"] = new_session_id
            forked_values["metadata"]["forked_from"] = source_session_id

        # Apply modifications
        if modifications:
            for key, value in modifications.items():
                forked_values[key] = value

        # Save to new thread
        new_config = {"configurable": {"thread_id": new_session_id}}
        await graph.aupdate_state(new_config, forked_values)

        logger.info(
            "Forked session %s -> %s at checkpoint %s",
            source_session_id,
            new_session_id,
            checkpoint_id,
        )

        return forked_values

    except Exception as e:
        logger.error("Failed to fork state: %s", e)
        return None


async def get_conversation_summary(
    graph: CompiledGraph,
    session_id: str,
) -> dict[str, Any]:
    """
    Get a summary of the conversation for debugging/support.

    Returns:
        Summary dict with key metrics and state info
    """
    config = {"configurable": {"thread_id": session_id}}

    try:
        current_state = await graph.aget_state(config)
        if not current_state:
            return {"error": "Session not found"}

        values = current_state.values

        # Count messages by role
        messages = values.get("messages", [])
        user_messages = sum(1 for m in messages if m.get("role") == "user")
        assistant_messages = sum(1 for m in messages if m.get("role") == "assistant")

        # Get history length
        history_count = 0
        async for _ in graph.aget_state_history(config, limit=100):
            history_count += 1

        return {
            "session_id": session_id,
            "current_state": values.get("current_state"),
            "detected_intent": values.get("detected_intent"),
            "step_number": values.get("step_number", 0),
            "message_count": {
                "user": user_messages,
                "assistant": assistant_messages,
                "total": len(messages),
            },
            "products": {
                "selected": len(values.get("selected_products", [])),
                "offered": len(values.get("offered_products", [])),
            },
            "errors": {
                "validation_errors": len(values.get("validation_errors", [])),
                "retry_count": values.get("retry_count", 0),
                "last_error": values.get("last_error"),
            },
            "flags": {
                "should_escalate": values.get("should_escalate", False),
                "awaiting_approval": values.get("awaiting_human_approval", False),
                "has_image": values.get("has_image", False),
            },
            "history_snapshots": history_count,
        }

    except Exception as e:
        logger.error("Failed to get conversation summary: %s", e)
        return {"error": str(e)}
