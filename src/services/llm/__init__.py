"""
LLM Service - High Availability Layer for LLM API calls.

Components:
- LLMFallbackService: Multi-provider fallback (OpenAI → OpenRouter)
- CircuitBreaker: Re-exported from src/core/circuit_breaker (SSOT)
"""

from src.core.circuit_breaker import CircuitBreaker, CircuitState

from .llm_fallback import LLMFallbackService, get_llm_service


__all__ = [
    # Core (re-exported for convenience)
    "CircuitBreaker",
    "CircuitState",
    # Service
    "LLMFallbackService",
    "get_llm_service",
]
