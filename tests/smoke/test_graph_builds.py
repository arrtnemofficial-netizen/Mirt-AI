"""
SMOKE: Test LangGraph compiles and builds correctly.

This is critical - if the graph can't build, nothing works.
"""

import pytest


@pytest.mark.smoke
@pytest.mark.critical
class TestGraphCompiles:
    """Verify LangGraph state machine compiles without error."""

    def test_production_graph_builds(self):
        """Production graph must compile successfully."""
        from src.agents.langgraph.graph import build_production_graph

        # Graph requires a runner function
        async def dummy_runner(state):
            return state

        graph = build_production_graph(runner=dummy_runner)
        assert graph is not None

    def test_graph_has_required_nodes(self):
        """Graph must have all required nodes defined."""
        from src.agents.langgraph.graph import build_production_graph

        async def dummy_runner(state):
            return state

        graph = build_production_graph(runner=dummy_runner)

        # Check compiled graph has nodes
        required_nodes = [
            "moderation",
            "intent",
            "agent",
            "vision",
            "offer",
            "payment",
            "escalation",
        ]

        graph_nodes = list(graph.nodes.keys())
        for node in required_nodes:
            assert node in graph_nodes, f"Missing node: {node}"

    def test_graph_has_entry_point(self):
        """Graph must have a valid entry point."""
        from src.agents.langgraph.graph import build_production_graph

        async def dummy_runner(state):
            return state

        graph = build_production_graph(runner=dummy_runner)
        # Graph should be invocable (has entry point configured)
        assert hasattr(graph, "invoke") or hasattr(graph, "stream")

    def test_initial_state_creates(self):
        """Initial state factory must work."""
        from src.agents.langgraph.state import create_initial_state

        state = create_initial_state(
            session_id="test_session", user_message="Привіт", metadata={"platform": "test"}
        )

        assert state is not None
        assert state["session_id"] == "test_session"
        assert state["current_state"] is not None


@pytest.mark.smoke
@pytest.mark.critical
class TestRoutingFunctions:
    """Verify routing functions work with basic inputs."""

    def test_master_router_callable(self):
        """Master router function is callable."""
        from src.agents.langgraph.edges import master_router

        assert callable(master_router)

    def test_route_after_intent_callable(self):
        """Route after intent function is callable."""
        from src.agents.langgraph.edges import route_after_intent

        assert callable(route_after_intent)

    def test_master_router_returns_valid_route(self):
        """Master router returns a valid route string."""
        from src.agents.langgraph.edges import master_router
        from src.core.state_machine import State

        # Minimal state for routing
        state = {
            "current_state": State.STATE_1_DISCOVERY.value,
            "detected_intent": None,
            "has_image": False,
            "is_escalated": False,
            "dialog_phase": None,
            "metadata": {},
        }

        route = master_router(state)
        assert isinstance(route, str)
        assert route in [
            "moderation",
            "intent",
            "agent",
            "vision",
            "offer",
            "payment",
            "escalation",
            "upsell",
            "__end__",
        ]
