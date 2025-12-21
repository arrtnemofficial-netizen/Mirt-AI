"""
Vision Node - Snippet Handling (Facade).
=======================================
Helper functions to retrieve text snippets from prompt registry.
Now simple re-exports from src.core.prompt_registry.
"""
from src.core.prompt_registry import get_snippet_by_header, get_product_snippet

__all__ = ["get_snippet_by_header", "get_product_snippet"]
