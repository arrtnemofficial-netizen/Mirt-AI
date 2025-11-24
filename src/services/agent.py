"""Pydantic AI agent configured with Grok 4.1 fast and catalog tool.

This module avoids network-heavy initialisation at import time. The agent is
constructed lazily so unit tests can supply a stub implementation without
requiring OpenRouter credentials.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.conf.config import settings
from src.core.models import AgentResponse
from src.services.catalog import CatalogService, get_catalog
from src.services.metadata import apply_metadata_defaults

SYSTEM_PROMPT_PATH = Path("data/system_prompt_full.yaml")


def load_system_prompt(path: Path = SYSTEM_PROMPT_PATH) -> str:
    """Load system prompt text from disk with a clear error if missing."""

    if not path.exists():
        raise FileNotFoundError(f"System prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


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
    catalog: CatalogService

    def __post_init__(self) -> None:
        @self.agent.tool  # type: ignore[misc]
        async def catalog_tool(query: str) -> List[Dict[str, Any]]:
            """Пошук товарів у каталозі MIRT за вільним описом."""

            return self.catalog.search_dicts(query)

        # Avoid linter warnings about unused inner function
        self._catalog_tool = catalog_tool

    async def run(self, history: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """Invoke the configured agent with message history and metadata."""

        if not history:
            raise ValueError("History must contain at least one user message")

        current_state = metadata.get("current_state") if metadata else "STATE0_INIT"
        prepared_metadata = apply_metadata_defaults(metadata, current_state)

        user_msg = history[-1]["content"]
        result = await self.agent.run(
            user_msg,
            model_settings={
                "extra_body": {
                    "reasoning": {"enabled": True, "effort": "medium"},
                    "metadata": prepared_metadata,
                }
            },
        )
        return result.data  # type: ignore[return-value]

    def run_sync(self, history: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """Synchronous convenience wrapper used by quick-start snippets."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run(history, metadata))
        else:
            return loop.run_until_complete(self.run(history, metadata))


def build_agent_runner(
    *,
    catalog: Optional[CatalogService] = None,
    system_prompt: Optional[str] = None,
    model: Optional[OpenAIModel] = None,
    retries: int = 2,
) -> AgentRunner:
    """Factory for the runtime AgentRunner."""

    catalog_instance = catalog or get_catalog()
    prompt = system_prompt or load_system_prompt()
    llm_model = model or build_model()

    pydantic_agent = Agent[None, AgentResponse](
        llm_model,
        system_prompt=prompt,
        retries=retries,
    )

    return AgentRunner(agent=pydantic_agent, catalog=catalog_instance)


# Lazily-instantiated default runner to avoid network calls on import
_default_runner: Optional[AgentRunner] = None


def get_default_runner() -> AgentRunner:
    global _default_runner
    if _default_runner is None:
        _default_runner = build_agent_runner()
    return _default_runner


async def run_agent(history: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> AgentResponse:
    """Runtime-friendly helper using the cached runner."""

    runner = get_default_runner()
    return await runner.run(history, metadata or {})


def run_agent_sync(history: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> AgentResponse:
    runner = get_default_runner()
    return runner.run_sync(history, metadata or {})


class DummyAgent:
    """Minimal stub used exclusively in tests."""

    def __init__(self, response: AgentResponse, capture: Optional[List[SimpleNamespace]] = None):
        self._response = response
        self._capture = capture if capture is not None else []

    def tool(self, func):  # noqa: ANN001
        return func

    async def run(self, *args, **kwargs):  # noqa: ANN001, D401
        self._capture.append(SimpleNamespace(args=args, kwargs=kwargs))
        return SimpleNamespace(data=self._response)

