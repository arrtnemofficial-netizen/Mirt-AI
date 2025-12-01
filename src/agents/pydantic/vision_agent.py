"""
Vision Agent - Photo analysis specialist.
==========================================
Handles photo identification and product matching.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.conf.config import settings
from src.core.prompt_loader import get_system_prompt_text

from .deps import AgentDeps
from .models import VisionResponse


logger = logging.getLogger(__name__)

# Vision guide path
VISION_GUIDE_PATH = Path(__file__).parent.parent.parent.parent / "data" / "vision_guide.json"


def _load_vision_guide() -> str:
    """Load vision recognition guide for better photo analysis."""
    try:
        if VISION_GUIDE_PATH.exists():
            with open(VISION_GUIDE_PATH, encoding="utf-8") as f:
                guide = json.load(f)
            return json.dumps(guide, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to load vision guide: %s", e)
    return ""


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
# VISION AGENT PROMPT
# =============================================================================


def _get_vision_prompt() -> str:
    """Build vision prompt with REAL catalog and recognition guide."""
    # Load full catalog from the same source as support_agent
    full_prompt = get_system_prompt_text("grok")

    # Load vision recognition guide
    vision_guide = _load_vision_guide()

    vision_instructions = """
# VISION AGENT - Аналіз фото товарів

Ти спеціаліст з розпізнавання товарів MIRT_UA (Ольга).

## ТВОЯ ЗАДАЧА:
1. Проаналізуй фото яке надіслав клієнт
2. Визнач товар з КАТАЛОГУ нижче (НЕ ВИГАДУЙ ТОВАРИ!)
3. Дай точну ціну та характеристики з каталогу
4. Запропонуй розмір якщо можеш визначити

## ФОРМАТ ВІДПОВІДІ:
- Якщо знайшов товар: опиши його, дай ціну, запитай розмір
- Якщо не впевнений: запропонуй схожі варіанти з каталогу
- Якщо не з каталогу: ввічливо поясни що не маємо такого

## ЗАБОРОНЕНО:
- Вигадувати товари яких немає в каталозі
- Називати ціни які не з каталогу
- Пропонувати кольори/розміри яких немає

Відповідай УКРАЇНСЬКОЮ, тепло як менеджер Ольга 🤍
"""

    # Build final prompt with vision guide
    if vision_guide:
        return f"{vision_instructions}\n---\n# VISION RECOGNITION GUIDE\n{vision_guide}\n\n---\n# CATALOG\n{full_prompt}"
    else:
        return f"{vision_instructions}\n---\n{full_prompt}"

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
            output_type=VisionResponse,  # Changed from result_type (PydanticAI 1.23+)
            system_prompt=_get_vision_prompt(),  # Use REAL catalog!
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
            timeout=120,  # Increased for slow API tiers
        )
        return result.output  # output_type param, result.output attr

    except Exception as e:
        logger.exception("Vision agent error: %s", e)
        return VisionResponse(
            reply_to_user="Вибачте, не вдалося проаналізувати фото. Спробуйте надіслати ще раз 🤍",
            confidence=0.0,
            needs_clarification=True,
            clarification_question="Чи можете надіслати фото ще раз або описати товар?",
        )
