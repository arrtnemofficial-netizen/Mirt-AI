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

__all__ = ["agent_node"]
