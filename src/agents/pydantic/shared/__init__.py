"""
Shared utilities for PydanticAI agents.
=======================================
Single Source of Truth for:
- Model factory (LLM provider selection)
- Catalog tools (product search)
- Payment prompts (requisites injection)
"""

from .catalog_tools import search_products_tool
from .model_factory import build_pydantic_model, get_ironclad_model_settings, IRONCLAD_MODEL, IRONCLAD_TEMPERATURE, IRONCLAD_REASONING_EFFORT
from .payment_prompts import add_payment_requisites

__all__ = [
    "build_pydantic_model",
    "get_ironclad_model_settings",
    "IRONCLAD_MODEL",
    "IRONCLAD_TEMPERATURE",
    "IRONCLAD_REASONING_EFFORT",
    "search_products_tool",
    "add_payment_requisites",
]
