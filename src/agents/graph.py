"""LangGraph orchestrator that wraps the Pydantic AI agent."""
from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph

from src.agents.nodes import ConversationState, agent_node
from src.agents.pydantic_agent import run_agent

if TYPE_CHECKING:
    from langgraph.graph.graph import CompiledGraph


def build_graph(runner=run_agent) -> "CompiledGraph":
    """Build the LangGraph state machine with the given agent runner."""
    graph = StateGraph(ConversationState)
    graph.add_node("agent", lambda state: agent_node(state, runner))
    graph.set_entry_point("agent")
    graph.add_edge("agent", END)
    return graph.compile()


# Lazy initialization - don't create at import time
_compiled_graph: "CompiledGraph | None" = None


def get_graph() -> "CompiledGraph":
    """Get or create the compiled graph (lazy singleton)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


class _LazyGraph:
    """Lazy proxy for backward compatibility with `app` usage."""

    _instance: "CompiledGraph | None" = None

    def __getattr__(self, name: str):
        if self._instance is None:
            self._instance = build_graph()
        return getattr(self._instance, name)

    async def ainvoke(self, *args, **kwargs):
        if self._instance is None:
            self._instance = build_graph()
        return await self._instance.ainvoke(*args, **kwargs)

    def invoke(self, *args, **kwargs):
        if self._instance is None:
            self._instance = build_graph()
        return self._instance.invoke(*args, **kwargs)


# Backward compatibility - lazy initialization
app = _LazyGraph()
