"""Agent package hosting prompts, nodes, and LangGraph wiring."""

from .graph_v2 import (
    ConversationStateV2 as ConversationState,
)
from .graph_v2 import (
    build_graph_v2 as build_graph,
)
from .graph_v2 import (
    get_active_graph,
)
from .graph_v2 import (
    get_graph_v2 as get_graph,
)
from .pydantic_agent import (
    AgentRunner,
    DummyAgent,
    build_agent_runner,
    get_default_runner,
    load_system_prompt,
    run_agent,
    run_agent_sync,
)


# Placeholder for app - deprecated, use get_active_graph()
app = None

# Re-export ConversationState as AgentState for backward compatibility
AgentState = ConversationState

__all__ = [
    "AgentRunner",
    "AgentState",
    "ConversationState",
    "DummyAgent",
    "app",
    "build_agent_runner",
    "build_graph",
    "get_active_graph",
    "get_default_runner",
    "get_graph",
    "load_system_prompt",
    "run_agent",
    "run_agent_sync",
]
