"""
Vision Node Package.
====================
Handles image identification and product matching.

Modules:
- node: Main orchestrator
- builder: UI response construction
- enricher: DB product enrichment
- snippets: Text snippet retrieval
"""

"""
Vision node public API.

Tests patch `src.agents.langgraph.nodes.vision.run_vision` to intercept the LLM call.
We export it here and make the node call it via this symbol.
"""

from src.agents.pydantic.vision_agent import run_vision

from .node import vision_node

__all__ = ["vision_node", "run_vision"]
