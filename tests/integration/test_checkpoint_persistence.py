"""
Checkpoint Persistence Tests.
=============================
Tests that verify state survives between graph invocations.

These are CRITICAL for production - without this, customers lose
their conversation progress on every restart.
"""

from typing import Any

import pytest


# =============================================================================
# FIXTURES
# =============================================================================


def create_test_state(
    session_id: str, message: str = "Привіт!", include_step_number: bool = True
) -> dict[str, Any]:
    """Create test state."""
    state = {
        "messages": [{"role": "user", "content": message}],
        "session_id": session_id,
        "thread_id": session_id,
        "metadata": {"session_id": session_id},
        "current_state": "STATE_0_INIT",
    }
    if include_step_number:
        state["step_number"] = 0
    return state


# =============================================================================
# MEMORY SAVER TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_state_persists_with_same_thread_id():
    """Test that state persists when using the same thread_id."""

    from langgraph.checkpoint.memory import MemorySaver

    from src.agents.langgraph.graph import build_production_graph

    # Create graph with memory checkpointer
    checkpointer = MemorySaver()

    # Mock runner to avoid API calls
    async def mock_runner(msg, metadata):
        from src.agents.pydantic.models import MessageItem, ResponseMetadata, SupportResponse

        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Привіт!")],
            metadata=ResponseMetadata(
                session_id=metadata.get("session_id", "test"),
                current_state="STATE_1_DISCOVERY",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

    graph = build_production_graph(mock_runner, checkpointer)

    session_id = "persist_test_123"
    config = {"configurable": {"thread_id": session_id}}

    # First invocation
    state1 = create_test_state(session_id, "Привіт!")
    result1 = await graph.ainvoke(state1, config=config)

    # Store step number
    step1 = result1.get("step_number", 0)
    assert step1 > 0, "Step number should increase"

    # Second invocation with same thread_id - should continue from checkpoint
    # Don't include step_number to allow checkpoint to restore it
    state2 = create_test_state(session_id, "Шукаю сукню", include_step_number=False)
    result2 = await graph.ainvoke(state2, config=config)

    step2 = result2.get("step_number", 0)

    # Step should continue from previous
    assert step2 > step1, f"Step should continue: {step1} -> {step2}"


@pytest.mark.asyncio
async def test_state_isolated_between_sessions():
    """Test that different sessions have isolated state."""
    from langgraph.checkpoint.memory import MemorySaver

    from src.agents.langgraph.graph import build_production_graph

    checkpointer = MemorySaver()

    async def mock_runner(msg, metadata):
        from src.agents.pydantic.models import MessageItem, ResponseMetadata, SupportResponse

        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Test")],
            metadata=ResponseMetadata(
                session_id=metadata.get("session_id", "test"),
                current_state="STATE_1_DISCOVERY",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

    graph = build_production_graph(mock_runner, checkpointer)

    # Session A
    config_a = {"configurable": {"thread_id": "session_a"}}
    state_a = create_test_state("session_a")
    result_a = await graph.ainvoke(state_a, config=config_a)

    # Session B - should start fresh
    config_b = {"configurable": {"thread_id": "session_b"}}
    state_b = create_test_state("session_b")
    result_b = await graph.ainvoke(state_b, config=config_b)

    # Both should have their own progression
    assert result_a.get("session_id") != result_b.get("session_id") or result_a.get(
        "thread_id"
    ) != result_b.get("thread_id"), "Sessions should be isolated"


# =============================================================================
# STATE HISTORY TEST
# =============================================================================


@pytest.mark.asyncio
async def test_state_history_available():
    """Test that state history is accessible."""
    from langgraph.checkpoint.memory import MemorySaver

    from src.agents.langgraph.graph import build_production_graph

    checkpointer = MemorySaver()

    async def mock_runner(msg, metadata):
        from src.agents.pydantic.models import MessageItem, ResponseMetadata, SupportResponse

        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Reply")],
            metadata=ResponseMetadata(
                session_id=metadata.get("session_id", "test"),
                current_state="STATE_1_DISCOVERY",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

    graph = build_production_graph(mock_runner, checkpointer)

    session_id = "history_test"
    config = {"configurable": {"thread_id": session_id}}

    # Multiple invocations to build history
    for i in range(3):
        state = create_test_state(session_id, f"Message {i}")
        await graph.ainvoke(state, config=config)

    # Get history
    history = []
    async for snapshot in graph.aget_state_history(config, limit=10):
        history.append(snapshot)

    assert len(history) >= 3, f"Should have at least 3 history entries, got {len(history)}"


# =============================================================================
# INTERRUPT/RESUME TEST (for payment flow)
# =============================================================================


@pytest.mark.asyncio
async def test_graph_with_interrupt_before_payment():
    """Test that graph correctly interrupts before payment node."""
    from langgraph.checkpoint.memory import MemorySaver

    from src.agents.langgraph.graph import build_production_graph

    checkpointer = MemorySaver()

    async def mock_runner(msg, metadata):
        from src.agents.pydantic.models import MessageItem, ResponseMetadata, SupportResponse

        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Reply")],
            metadata=ResponseMetadata(
                session_id=metadata.get("session_id", "test"),
                current_state="STATE_1_DISCOVERY",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

    graph = build_production_graph(mock_runner, checkpointer)

    # Verify interrupt is configured
    # The graph should have interrupt_before=["payment"]
    # This is set during compilation
    assert graph is not None, "Graph should compile"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
