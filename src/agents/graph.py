"""LangGraph orchestrator that wraps the Pydantic AI agent."""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.agents.nodes import AgentState, agent_node
from src.agents.pydantic_agent import run_agent


def build_graph(runner=run_agent):
    graph = StateGraph(AgentState)
    graph.add_node("agent", lambda state: agent_node(state, runner))
    graph.set_entry_point("agent")
    graph.add_edge("agent", END)
    return graph.compile()


app = build_graph()
