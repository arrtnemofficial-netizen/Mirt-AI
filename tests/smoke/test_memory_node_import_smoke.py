"""SMOKE: memory node and state imports must stay resolvable."""

import pytest


@pytest.mark.smoke
@pytest.mark.critical
def test_memory_node_and_state_imports() -> None:
    from src.agents.langgraph.nodes.memory import memory_context_node, memory_update_node
    from src.agents.langgraph.state import create_initial_state

    state = create_initial_state(session_id="SMOKE-MEMORY")

    assert callable(memory_context_node)
    assert callable(memory_update_node)
    assert getattr(state, "session_id", None) == "SMOKE-MEMORY"
