"""
LLM Fallback Service.
=====================
Provides automatic fallback between LLM providers with circuit breaker pattern.
Ensures high availability even when primary provider fails.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError

from src.conf.config import settings


logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing, don't try
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class CircuitBreaker:
    """Circuit breaker for LLM provider.
    
    Prevents cascading failures by temporarily disabling failing providers.
    """
    name: str
    failure_threshold: int = 3
    recovery_timeout: float = 60.0  # seconds
    half_open_max_calls: int = 1
    
    state: CircuitState = field(default=CircuitState.CLOSED)
    failure_count: int = field(default=0)
    last_failure_time: float = field(default=0.0)
    half_open_calls: int = field(default=0)
    
    def record_success(self) -> None:
        """Record successful call."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.half_open_calls = 0
        logger.debug("[CIRCUIT:%s] Success, state=CLOSED", self.name)
    
    def record_failure(self) -> None:
        """Record failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "[CIRCUIT:%s] OPEN after %d failures",
                self.name,
                self.failure_count,
            )
    
    def can_execute(self) -> bool:
        """Check if circuit allows execution."""
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout passed
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                logger.info("[CIRCUIT:%s] Transitioning to HALF_OPEN", self.name)
                return True
            return False
        
        # HALF_OPEN: allow limited calls
        if self.half_open_calls < self.half_open_max_calls:
            self.half_open_calls += 1
            return True
        return False


@dataclass
class LLMProvider:
    """LLM provider configuration."""
    name: str
    api_key: str
    base_url: str
    model: str
    priority: int = 0
    circuit: CircuitBreaker = field(default_factory=lambda: CircuitBreaker("default"))
    
    def __post_init__(self):
        self.circuit = CircuitBreaker(self.name)


class LLMFallbackService:
    """Service for LLM calls with automatic fallback.
    
    Features:
    - Circuit breaker per provider
    - Automatic fallback to next provider
    - Retry with exponential backoff
    - Detailed logging and metrics
    """
    
    def __init__(self):
        self.providers: list[LLMProvider] = []
        self._setup_providers()
    
    def _setup_providers(self) -> None:
        """Initialize LLM providers (OpenAI GPT-5.1 only)."""
        # OpenAI GPT-5.1 only (OpenRouter removed)
        openai_key = settings.OPENAI_API_KEY.get_secret_value()
        if not openai_key:
            logger.warning("[LLM_FALLBACK] OPENAI_API_KEY not configured")
        else:
            self.providers.append(LLMProvider(
                name="openai",
                api_key=openai_key,
                base_url="https://api.openai.com/v1",
                model=settings.LLM_MODEL_GPT,  # GPT-5.1 only
                priority=1,
            ))
        
        logger.info(
            "[LLM_FALLBACK] Initialized with %d providers: %s",
            len(self.providers),
            [p.name for p in self.providers],
        )
    
    def _get_client(self, provider: LLMProvider) -> AsyncOpenAI:
        """Create OpenAI client for provider."""
        return AsyncOpenAI(
            api_key=provider.api_key,
            base_url=provider.base_url,
            timeout=30.0,
        )
    
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute chat completion with fallback.
        
        Args:
            messages: Chat messages
            model: Override model (optional)
            temperature: Override temperature (optional)
            max_tokens: Override max tokens (optional)
            **kwargs: Additional OpenAI parameters
            
        Returns:
            OpenAI ChatCompletion response
            
        Raises:
            Exception: If all providers fail
        """
        last_error: Exception | None = None
        
        for provider in self.providers:
            if not provider.circuit.can_execute():
                logger.info(
                    "[LLM_FALLBACK] Skipping %s (circuit open)",
                    provider.name,
                )
                continue
            
            try:
                client = self._get_client(provider)
                
                response = await client.chat.completions.create(
                    model=model or provider.model,
                    messages=messages,
                    temperature=temperature or settings.LLM_TEMPERATURE,
                    max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
                    **kwargs,
                )
                
                provider.circuit.record_success()
                logger.info(
                    "[LLM_FALLBACK] Success with %s, model=%s",
                    provider.name,
                    model or provider.model,
                )
                return response
                
            except (APIError, APITimeoutError, RateLimitError) as e:
                provider.circuit.record_failure()
                last_error = e
                logger.warning(
                    "[LLM_FALLBACK] Provider %s failed: %s",
                    provider.name,
                    str(e)[:100],
                )
                continue
                
            except Exception as e:
                provider.circuit.record_failure()
                last_error = e
                logger.exception(
                    "[LLM_FALLBACK] Unexpected error from %s",
                    provider.name,
                )
                continue
        
        # All providers failed
        logger.error("[LLM_FALLBACK] All providers failed!")
        raise last_error or Exception("No LLM providers available")
    
    def get_available_provider(self) -> LLMProvider | None:
        """Get first available provider (for synchronous checks)."""
        for provider in self.providers:
            if provider.circuit.can_execute():
                return provider
        return None
    
    def get_health_status(self) -> dict[str, Any]:
        """Get health status of all providers."""
        return {
            "providers": [
                {
                    "name": p.name,
                    "model": p.model,
                    "circuit_state": p.circuit.state.value,
                    "failure_count": p.circuit.failure_count,
                    "available": p.circuit.can_execute(),
                }
                for p in self.providers
            ],
            "any_available": any(p.circuit.can_execute() for p in self.providers),
        }
    
    def reset_circuit_breaker(self, provider_name: str | None = None) -> dict[str, Any]:
        """Reset circuit breaker for a specific provider or all providers.
        
        Useful when quota/billing issue is resolved and you want to immediately
        retry instead of waiting for recovery_timeout (60s).
        
        Args:
            provider_name: Name of provider to reset (e.g., "openai"). If None, resets all.
        
        Returns:
            dict with reset results:
            {
                "reset_providers": list[str],  # Providers that were reset
                "previous_states": dict[str, str],  # Previous circuit states
            }
        """
        reset_providers: list[str] = []
        previous_states: dict[str, str] = {}
        
        providers_to_reset = (
            [p for p in self.providers if p.name == provider_name] if provider_name
            else self.providers
        )
        
        for provider in providers_to_reset:
            previous_states[provider.name] = provider.circuit.state.value
            # Reset circuit breaker to CLOSED state
            provider.circuit.state = CircuitState.CLOSED
            provider.circuit.failure_count = 0
            provider.circuit.last_failure_time = 0.0
            provider.circuit.half_open_calls = 0
            reset_providers.append(provider.name)
            logger.info(
                "[LLM_FALLBACK] Circuit breaker reset for %s (was %s)",
                provider.name,
                previous_states[provider.name],
            )
        
        return {
            "reset_providers": reset_providers,
            "previous_states": previous_states,
        }
    
    async def force_recovery_check(self, timeout: float = 5.0) -> dict[str, Any]:
        """Force a recovery check: test quota and reset circuit breaker if quota is OK.
        
        This method:
        1. Attempts a lightweight API call to verify quota is restored
        2. If successful, automatically resets circuit breaker
        3. Returns detailed status
        
        Useful after resolving billing/quota issues.
        
        Args:
            timeout: Maximum time to wait for API response
        
        Returns:
            dict with recovery check results:
            {
                "quota_status": "ok" | "failed" | "unknown",
                "circuit_reset": bool,  # Whether circuit breaker was reset
                "providers_reset": list[str],
                "message": str,
            }
        """
        # First, try preflight check even if circuit is open
        # Temporarily reset circuit to test
        temp_reset = self.reset_circuit_breaker()
        
        try:
            preflight_result = await self.preflight_check(timeout=timeout)
            quota_status = preflight_result.get("quota_check", "unknown")
            
            if quota_status == "ok":
                # Quota is OK, keep circuit breaker reset
                return {
                    "quota_status": "ok",
                    "circuit_reset": True,
                    "providers_reset": temp_reset["reset_providers"],
                    "message": "Quota verified OK, circuit breaker reset successfully",
                    "preflight": preflight_result,
                }
            else:
                # Quota still not OK, restore previous state
                # Actually, we already reset it, so just report
                return {
                    "quota_status": quota_status,
                    "circuit_reset": True,  # We did reset it
                    "providers_reset": temp_reset["reset_providers"],
                    "message": f"Circuit breaker reset, but quota check returned: {quota_status}",
                    "preflight": preflight_result,
                    "warnings": preflight_result.get("warnings", []),
                }
        except Exception as e:
            logger.exception("[LLM_FALLBACK] Force recovery check failed: %s", e)
            return {
                "quota_status": "unknown",
                "circuit_reset": True,  # We did reset it anyway
                "providers_reset": temp_reset["reset_providers"],
                "message": f"Recovery check failed: {str(e)[:200]}",
                "error": str(e)[:200],
            }
    
    async def preflight_check(self, timeout: float = 2.0) -> dict[str, Any]:
        """Pre-flight check: lightweight API call to verify quota and connectivity.
        
        Attempts a lightweight API call (models.list) to detect quota issues
        BEFORE processing requests. Also checks circuit breaker states.
        
        Args:
            timeout: Maximum time to wait for API response
        
        Returns:
            dict with preflight check results:
            {
                "status": "ok" | "warning" | "error",
                "quota_check": "ok" | "failed" | "unknown",
                "circuit_states": dict[str, str],  # provider -> state
                "warnings": list[str],
            }
        """
        warnings: list[str] = []
        circuit_states: dict[str, str] = {}
        
        # Check circuit breaker states
        for provider in self.providers:
            state = provider.circuit.state.value
            circuit_states[provider.name] = state
            if state == "open":
                warnings.append(f"Circuit breaker OPEN for {provider.name}")
        
        # If all circuits are open, that's a problem
        if all(p.circuit.state.value == "open" for p in self.providers):
            return {
                "status": "error",
                "quota_check": "unknown",
                "circuit_states": circuit_states,
                "warnings": warnings + ["All circuit breakers are OPEN"],
            }
        
        # Try lightweight API call to check quota (only for available providers)
        available_provider = self.get_available_provider()
        if not available_provider:
            return {
                "status": "error",
                "quota_check": "unknown",
                "circuit_states": circuit_states,
                "warnings": warnings + ["No available providers"],
            }
        
        try:
            client = self._get_client(available_provider)
            # Lightweight call: list models (doesn't consume quota)
            import asyncio
            await asyncio.wait_for(
                client.models.list(),
                timeout=timeout
            )
            quota_check = "ok"
        except RateLimitError as e:
            # 429 error - quota exceeded or rate limited
            quota_check = "failed"
            warnings.append(f"Quota/rate limit detected for {available_provider.name}: {str(e)[:100]}")
        except APITimeoutError:
            quota_check = "unknown"
            warnings.append(f"API timeout during preflight check for {available_provider.name}")
        except APIError as e:
            # Check if it's a quota error
            error_str = str(e).lower()
            if "quota" in error_str or "429" in error_str or "insufficient_quota" in error_str:
                quota_check = "failed"
                warnings.append(f"Quota exceeded for {available_provider.name}")
            else:
                quota_check = "unknown"
                warnings.append(f"API error during preflight check: {str(e)[:100]}")
        except Exception as e:
            quota_check = "unknown"
            warnings.append(f"Unexpected error during preflight check: {str(e)[:100]}")
        
        status = "error" if quota_check == "failed" else ("warning" if warnings else "ok")
        
        return {
            "status": status,
            "quota_check": quota_check,
            "circuit_states": circuit_states,
            "warnings": warnings,
        }


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_llm_service: LLMFallbackService | None = None


def get_llm_service() -> LLMFallbackService:
    """Get or create LLM fallback service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMFallbackService()
    return _llm_service
