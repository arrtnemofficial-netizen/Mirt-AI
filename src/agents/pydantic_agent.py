"""Pydantic AI agent configured with Grok 4.1 fast and Supabase tools.

This module lives under the ``agents`` package to keep the model, prompt,
operations, and LangGraph orchestration co-located. It mirrors the previous
service-layer implementation while keeping import side-effects minimal.
"""
from __future__ import annotations

import asyncio
import logging
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
from src.services.metadata import apply_metadata_defaults
from src.services.supabase_tools import SupabaseProductTools, get_supabase_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = Path("data/system_prompt_full.yaml")

# Таймаут на LLM виклик (захист від зависання OpenRouter)
LLM_TIMEOUT_SECONDS = 30


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
    tools: SupabaseProductTools

    def __post_init__(self) -> None:
        @self.agent.tool(name="T_SUPABASE_SEARCH_BY_QUERY")  # type: ignore[misc]
        async def supabase_search_by_query(user_query: str, match_count: int = 5) -> List[Dict[str, Any]]:
            """Семантичний пошук моделей у Supabase за текстовим описом."""

            return await self.tools.search_by_query(user_query, match_count=match_count)

        @self.agent.tool(name="T_SUPABASE_GET_BY_ID")  # type: ignore[misc]
        async def supabase_get_by_id(product_id: str) -> List[Dict[str, Any]]:
            """Отримати конкретну модель за product_id."""

            return await self.tools.get_by_id(product_id)

        @self.agent.tool(name="T_SUPABASE_GET_BY_PHOTO_URL")  # type: ignore[misc]
        async def supabase_get_by_photo_url(photo_url: str) -> List[Dict[str, Any]]:
            """Знайти модель за канонічним фото каталогу."""

            return await self.tools.get_by_photo_url(photo_url)

        # Avoid linter warnings about unused inner functions
        self._supabase_search_by_query = supabase_search_by_query
        self._supabase_get_by_id = supabase_get_by_id
        self._supabase_get_by_photo_url = supabase_get_by_photo_url

    async def run(self, history: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> AgentResponse:
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
            return result.data  # type: ignore[return-value]
        except asyncio.TimeoutError:
            logger.error("LLM timeout after %d seconds for session %s", LLM_TIMEOUT_SECONDS, session_id)
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
            escalation=Escalation(reason="LLM_TIMEOUT", target="admin"),
        )

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
    tools: Optional[SupabaseProductTools] = None,
    system_prompt: Optional[str] = None,
    model: Optional[OpenAIModel] = None,
    retries: int = 2,
) -> AgentRunner:
    """Factory for the runtime AgentRunner."""

    tools_instance = tools or get_supabase_tools()
    if tools_instance is None:
        raise RuntimeError("Supabase client is not configured; cannot build agent tools")
    prompt = system_prompt or load_system_prompt()
    llm_model = model or build_model()

    pydantic_agent = Agent[None, AgentResponse](
        llm_model,
        system_prompt=prompt,
        retries=retries,
    )

    return AgentRunner(agent=pydantic_agent, tools=tools_instance)


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

    def tool(self, func=None, *, name: Optional[str] = None):  # noqa: ANN001
        """Mock tool decorator that accepts optional name kwarg like real Agent."""
        def decorator(f):
            return f
        if func is not None:
            return decorator(func)
        return decorator

    async def run(self, *args, **kwargs):  # noqa: ANN001, D401
        self._capture.append(SimpleNamespace(args=args, kwargs=kwargs))
        return SimpleNamespace(data=self._response)
