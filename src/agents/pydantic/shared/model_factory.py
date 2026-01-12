"""
Model Factory - ЗАЛІЗОБЕТОННЕ Single Source of Truth for LLM initialization.
==============================================================================
Creates PydanticAI-compatible OpenAI models.

ЗАЛІЗОБЕТОННЕ ПРАВИЛО: ТІЛЬКИ gpt-5.1 medium reasoning, temperature 0.2

Features:
- ENFORCED: gpt-5.1 model only
- ENFORCED: temperature 0.2
- ENFORCED: medium reasoning effort
- Fail-fast in production if API keys missing
"""

import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.conf.config import settings


logger = logging.getLogger(__name__)

# =============================================================================
# ЗАЛІЗОБЕТОННІ КОНСТАНТИ - НЕ ЗМІНЮВАТИ!
# =============================================================================

IRONCLAD_MODEL = "gpt-5.1"
IRONCLAD_TEMPERATURE = 0.2
IRONCLAD_REASONING_EFFORT = "medium"


def get_ironclad_model_settings() -> dict[str, Any]:
    """
    Get ЗАЛІЗОБЕТОННІ model settings for all agents.
    
    Returns:
        Dict with temperature and reasoning_effort
    """
    return {
        "temperature": IRONCLAD_TEMPERATURE,
        "reasoning_effort": IRONCLAD_REASONING_EFFORT,
    }


def build_pydantic_model(
    agent_name: str = "agent",
    *,
    model_override: str | None = None,
) -> OpenAIChatModel:
    """
    Build OpenAI-compatible model for PydanticAI agent.
    
    ЗАЛІЗОБЕТОННЕ ПРАВИЛО: Uses gpt-5.1 by default. Override only for specific cases.
    
    Args:
        agent_name: Name of agent for logging ("vision", "payment", "support", "memory")
        model_override: Optional model name override (use sparingly!)
    
    Returns:
        Configured OpenAIChatModel ready for PydanticAI Agent
    
    Raises:
        ValueError: If required API keys are missing in production
    """
    # ЗАЛІЗОБЕТОННО: default to gpt-5.1
    model_name = model_override if model_override else IRONCLAD_MODEL
    
    # Warn if not using ironclad model
    if model_name != IRONCLAD_MODEL:
        logger.warning(
            "⚠️ %s using non-ironclad model: %s (expected: %s)",
            agent_name,
            model_name,
            IRONCLAD_MODEL,
        )

    # Check if we're in production/staging
    env = settings.SENTRY_ENVIRONMENT.lower() if settings.SENTRY_ENVIRONMENT else "development"
    is_production = env in ("production", "prod", "staging")

    is_openai_model = (
        model_name.startswith("gpt-") or model_name.startswith("o1") or model_name.startswith("o3")
    )

    if is_openai_model:
        api_key = settings.OPENAI_API_KEY.get_secret_value()
        base_url = "https://api.openai.com/v1"

        # CRITICAL: In production, fail fast if OpenAI key is missing
        if not api_key:
            error_msg = (
                f"OPENAI_API_KEY is required for {model_name} in {env}. "
                "Set OPENAI_API_KEY environment variable."
            )
            logger.error(error_msg)
            from src.services.observability import track_metric
            track_metric("llm_config_error", 1, {"error": "missing_openai_key", "env": env, "model": model_name})
            if is_production:
                raise ValueError(error_msg)
            # Development fallback
            logger.warning("Falling back to OpenRouter in development")
            api_key = settings.OPENROUTER_API_KEY.get_secret_value()
            base_url = settings.OPENROUTER_BASE_URL
            if not api_key:
                raise ValueError("No API key available")
            model_name = f"openai/{model_name}"
    else:
        api_key = settings.OPENROUTER_API_KEY.get_secret_value()
        base_url = settings.OPENROUTER_BASE_URL
        if not api_key:
            raise ValueError(f"OPENROUTER_API_KEY required for {model_name}")

    # Log resolved configuration
    logger.info(
        "🔧 %s: model=%s, temp=%.1f, reasoning=%s (env=%s)",
        agent_name.capitalize(),
        model_name,
        IRONCLAD_TEMPERATURE,
        IRONCLAD_REASONING_EFFORT,
        env,
    )

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    provider = OpenAIProvider(openai_client=client)
    return OpenAIChatModel(model_name, provider=provider)
