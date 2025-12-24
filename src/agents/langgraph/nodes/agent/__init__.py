"""
Generic Agent Package.
=====================
Modularized agent node handling discovery, sizing, and ordering.

Modules:
- node: Main orchestrator
- logic: Business rules and state machine
- tools: Pure logic helpers (math/regex)
- catalog: Data access interfaces
"""

from .node import agent_node

"""
Backward-compatibility exports.

Tests (and some legacy integration points) patch `src.agents.langgraph.nodes.agent.run_support`.
After the refactor we call `run_main` directly inside the node. We keep `run_support`
as a stable alias to make patching and older call sites work.
"""

from src.agents.pydantic.main_agent import run_main as run_support

__all__ = ["agent_node", "run_support"]
