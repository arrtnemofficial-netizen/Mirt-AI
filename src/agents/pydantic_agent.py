"""Pydantic AI agent configured with Grok 4.1 fast; Supabase tools вимкнені.

This module lives under the ``agents`` package to keep the model, prompt,
operations, and LangGraph orchestration co-located. It mirrors the previous
service-layer implementation while keeping import side-effects minimal.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.conf.config import settings
from src.core.models import AgentResponse
from src.services.metadata import apply_metadata_defaults


logger = logging.getLogger(__name__)

# Таймаут на LLM виклик (захист від зависання OpenRouter)
LLM_TIMEOUT_SECONDS = 30


def load_system_prompt(model_key: str = "grok") -> str:
    """
    Load system prompt text for the specified LLM model.

    Uses the new prompt_loader which merges base.yaml + model-specific config
    and generates an optimized system prompt.

    Args:
        model_key: One of "grok", "gpt", "gemini"

    Returns:
        Formatted system prompt string
    """
    from src.core.prompt_loader import get_system_prompt_text

    return get_system_prompt_text(model_key)


def build_model() -> OpenAIModel:
    """Create an OpenAIModel that targets Grok via OpenRouter."""

    api_key = settings.OPENROUTER_API_KEY.get_secret_value()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is missing; cannot build AI model")

    client = AsyncOpenAI(base_url=settings.OPENROUTER_BASE_URL, api_key=api_key)
    provider = OpenAIProvider(openai_client=client)
    return OpenAIModel(settings.AI_MODEL, provider=provider)


@dataclass
class AgentRunner:
    """Wrapper around the pydantic-ai Agent to simplify testing and DI."""

    agent: Agent
    tools: Any | None = None  # Supabase tools вимкнені

    def __post_init__(self) -> None:
        # Tools не реєструємо: працюємо без Supabase (Embedded Catalog).
        pass

    async def run(
        self, history: list[dict[str, Any]], metadata: dict[str, Any] | None = None
    ) -> AgentResponse:
        """Invoke the configured agent with message history and metadata."""

        if not history:
            raise ValueError("History must contain at least one user message")

        current_state = metadata.get("current_state") if metadata else "STATE0_INIT"
        prepared_metadata = apply_metadata_defaults(metadata, current_state)
        session_id = metadata.get("session_id", "") if metadata else ""

        user_msg = history[-1]["content"]

        try:
            # Таймаут захищає від зависання при проблемах з OpenRouter
            result = await asyncio.wait_for(
                self.agent.run(
                    user_msg,
                    model_settings={
                        "extra_body": {
                            "reasoning": {"enabled": True, "effort": "medium"},
                            "metadata": prepared_metadata,
                        }
                    },
                ),
                timeout=LLM_TIMEOUT_SECONDS,
            )
            # pydantic-ai 1.0+ uses .output instead of .data
            output = result.output

            # If LLM returned raw JSON string, parse it
            if isinstance(output, str):
                import json

                try:
                    data = json.loads(output)
                    return AgentResponse.model_validate(data)
                except (json.JSONDecodeError, Exception) as parse_err:
                    logger.warning("Failed to parse LLM output as JSON: %s", parse_err)
                    # Return as text message
                    from src.core.models import Message, Metadata

                    return AgentResponse(
                        event="simple_answer",
                        messages=[Message(type="text", content=output)],
                        products=[],
                        metadata=Metadata(
                            session_id=session_id,
                            current_state=current_state,
                            intent="UNKNOWN_OR_EMPTY",
                        ),
                    )

            return output  # type: ignore[return-value]
        except TimeoutError:
            logger.error(
                "LLM timeout after %d seconds for session %s", LLM_TIMEOUT_SECONDS, session_id
            )
            return self._build_timeout_response(session_id, current_state)

    def _build_timeout_response(self, session_id: str, current_state: str) -> AgentResponse:
        """Build graceful fallback response when LLM times out."""
        from src.core.models import Escalation, Message, Metadata

        return AgentResponse(
            event="escalation",
            messages=[
                Message(
                    type="text",
                    content="Вибачте, система тимчасово перевантажена. Спробуйте ще раз через хвилину або напишіть менеджеру 🤍",
                )
            ],
            products=[],
            metadata=Metadata(
                session_id=session_id,
                current_state=current_state,
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L1",
            ),
            escalation=Escalation(level="L1", reason="LLM_TIMEOUT", target="admin"),
        )

    def run_sync(
        self, history: list[dict[str, Any]], metadata: dict[str, Any] | None = None
    ) -> AgentResponse:
        """Synchronous convenience wrapper used by quick-start snippets."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run(history, metadata))
        else:
            return loop.run_until_complete(self.run(history, metadata))


def _get_model_key_from_settings() -> str:
    """
    Determine model key based on current LLM provider settings.

    Returns:
        Model key: "grok", "gpt", or "gemini"
    """
    provider = getattr(settings, "LLM_PROVIDER", "openrouter").lower()
    provider_to_key = {
        "openrouter": "grok",
        "openai": "gpt",
        "google": "gemini",
    }
    return provider_to_key.get(provider, "grok")


def build_agent_runner(
    *,
    tools: Any | None = None,
    system_prompt: str | None = None,
    model: OpenAIModel | None = None,
    retries: int = 2,
) -> AgentRunner:
    """Factory for the runtime AgentRunner (Supabase tools відключені)."""

    tools_instance = tools  # kept for API compatibility; не використовується
    # Визначити model_key з settings
    model_key = _get_model_key_from_settings()
    prompt = system_prompt or load_system_prompt(model_key)
    llm_model = model or build_model()

    pydantic_agent = Agent[None, AgentResponse](
        llm_model,
        system_prompt=prompt,
        retries=retries,
    )

    return AgentRunner(agent=pydantic_agent, tools=tools_instance)


# Lazily-instantiated default runner to avoid network calls on import
_default_runner: AgentRunner | None = None


def get_default_runner() -> AgentRunner:
    global _default_runner
    if _default_runner is None:
        _default_runner = build_agent_runner()
    return _default_runner


async def run_agent(
    history: list[dict[str, Any]], metadata: dict[str, Any] | None = None
) -> AgentResponse:
    """Runtime-friendly helper using the cached runner."""

    runner = get_default_runner()
    return await runner.run(history, metadata or {})


def run_agent_sync(
    history: list[dict[str, Any]], metadata: dict[str, Any] | None = None
) -> AgentResponse:
    runner = get_default_runner()
    return runner.run_sync(history, metadata or {})


class DummyAgent:
    """Minimal stub used exclusively in tests."""

    def __init__(self, response: AgentResponse, capture: list[SimpleNamespace] | None = None):
        self._response = response
        self._capture = capture if capture is not None else []

    def tool(self, func=None, *, name: str | None = None):
        """Mock tool decorator that accepts optional name kwarg like real Agent."""

        def decorator(f):
            return f

        if func is not None:
            return decorator(func)
        return decorator

    async def run(self, *args, **kwargs):
        self._capture.append(SimpleNamespace(args=args, kwargs=kwargs))
        return SimpleNamespace(data=self._response)
