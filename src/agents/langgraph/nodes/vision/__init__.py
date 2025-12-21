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

from .node import vision_node

__all__ = ["vision_node"]
