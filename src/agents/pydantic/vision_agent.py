"""
Vision Agent - Photo analysis specialist.
==========================================
Handles photo identification and product matching.
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.conf.config import settings

from .deps import AgentDeps
from .models import VisionResponse


logger = logging.getLogger(__name__)


# =============================================================================
# MODEL SETUP
# =============================================================================


def _build_model() -> OpenAIModel:
    """Build OpenAI model."""
    api_key = settings.OPENROUTER_API_KEY.get_secret_value()
    client = AsyncOpenAI(base_url=settings.OPENROUTER_BASE_URL, api_key=api_key)
    provider = OpenAIProvider(openai_client=client)
    return OpenAIModel(settings.AI_MODEL, provider=provider)


# =============================================================================
# VISION AGENT
# =============================================================================


_vision_prompt = """
Ти спеціаліст з розпізнавання товарів MIRT_UA.

ТВОЯ ЗАДАЧА:
1. Проаналізуй фото яке надіслав клієнт
2. Визнач товар з КАТАЛОГУ (сукні, костюми, тренчі)
3. Дай точну ціну та характеристики
4. Запропонуй розмір якщо можеш

КАТАЛОГ MIRT_UA:
- Сукня "Еліт" - 1300 грн (рожева, чорна, молочна)
- Сукня "Анна" - 1200 грн (пудра, чорна)
- Костюм "Стелла" - 1400 грн (рожевий, сірий)
- Тренч "Класик" - 1600 грн (бежевий, чорний)
- Сукня "Перлина" - 1500 грн (біла, рожева)

ФОРМАТ ВІДПОВІДІ:
- Якщо знайшов товар: опиши його, дай ціну, запитай розмір
- Якщо не впевнений: запропонуй схожі варіанти
- Якщо не з каталогу: ввічливо поясни що не маємо

Відповідай УКРАЇНСЬКОЮ, тепло як менеджер Ольга 🤍
"""

_vision_agent: Agent[AgentDeps, VisionResponse] | None = None


async def _add_image_url(ctx: RunContext[AgentDeps]) -> str:
    """Add image URL to prompt."""
    if ctx.deps.image_url:
        return f"\n[IMAGE_URL: {ctx.deps.image_url}]"
    return ""


def get_vision_agent() -> Agent[AgentDeps, VisionResponse]:
    """Get or create vision agent (lazy initialization)."""
    global _vision_agent
    if _vision_agent is None:
        _vision_agent = Agent(  # type: ignore[call-overload]
            _build_model(),
            deps_type=AgentDeps,
            result_type=VisionResponse,
            system_prompt=_vision_prompt,
            retries=2,
        )
        _vision_agent.system_prompt(_add_image_url)
    return _vision_agent


# Backward compatibility - removed unused property


# =============================================================================
# RUNNER
# =============================================================================


async def run_vision(
    message: str,
    deps: AgentDeps,
    message_history: list[Any] | None = None,
) -> VisionResponse:
    """
    Run vision agent for photo analysis.

    Args:
        message: User message with photo context
        deps: Dependencies (must have image_url)
        message_history: Previous messages

    Returns:
        Validated VisionResponse
    """
    import asyncio

    agent = get_vision_agent()

    # Add image context to message
    if deps.image_url and "[IMAGE_URL:" not in message:
        message = f"{message}\n\n[IMAGE_URL: {deps.image_url}]"

    try:
        result = await asyncio.wait_for(
            agent.run(message, deps=deps, message_history=message_history),
            timeout=30,
        )
        return result.output

    except Exception as e:
        logger.exception("Vision agent error: %s", e)
        return VisionResponse(
            reply_to_user="Вибачте, не вдалося проаналізувати фото. Спробуйте надіслати ще раз 🤍",
            confidence=0.0,
            needs_clarification=True,
            clarification_question="Чи можете надіслати фото ще раз або описати товар?",
        )
