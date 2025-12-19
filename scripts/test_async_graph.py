#!/usr/bin/env python
"""Test graph creation in async context (like production FastAPI)."""

import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_graph():
    """Test graph creation in async context."""
    from src.agents.langgraph.graph import get_production_graph

    g = get_production_graph()
    print(f"✅ Graph created with {len(g.nodes)} nodes")
    print(f"   Nodes: {list(g.nodes.keys())}")
    return True


if __name__ == "__main__":
    result = asyncio.run(test_graph())
    sys.exit(0 if result else 1)
