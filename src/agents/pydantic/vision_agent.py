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
from src.core.prompt_registry import registry

from .deps import AgentDeps
from .models import VisionResponse


logger = logging.getLogger(__name__)

# Vision guide logic replaced by prompt registry


# =============================================================================
# MODEL SETUP
# =============================================================================


def _build_model() -> OpenAIModel:
    """Build OpenAI model."""
    if settings.LLM_PROVIDER == "openai":
        api_key = settings.OPENAI_API_KEY.get_secret_value()
        base_url = "https://api.openai.com/v1"
        model_name = settings.LLM_MODEL_GPT
    else:
        api_key = settings.OPENROUTER_API_KEY.get_secret_value()
        base_url = settings.OPENROUTER_BASE_URL
        model_name = settings.LLM_MODEL_GROK if settings.LLM_PROVIDER == "openrouter" else settings.AI_MODEL

    if not api_key:
        logger.warning("API Key missing for provider %s", settings.LLM_PROVIDER)
        if settings.LLM_PROVIDER == "openai":
             api_key = settings.OPENROUTER_API_KEY.get_secret_value()
             base_url = settings.OPENROUTER_BASE_URL
             model_name = settings.AI_MODEL

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    provider = OpenAIProvider(openai_client=client)
    return OpenAIModel(model_name, provider=provider)


# =============================================================================
# VISION AGENT PROMPT
# =============================================================================


async def _search_products(
    ctx: RunContext[AgentDeps],
    query: str,
    category: str | None = None,
) -> str:
    """
    Знайти товари в каталозі.

    Використовуй це щоб знайти товар який ти бачиш на фото.
    Наприклад: search_products("рожева сукня") або search_products("костюм з лампасами")
    """
    products = await ctx.deps.catalog.search_products(query, category)

    if not products:
        return "На жаль, за вашим запитом нічого не знайдено."

    lines = ["Знайдені товари:"]
    for p in products:
        name = p.get("name")
        price = p.get("price")
        sizes = ", ".join(p.get("sizes", []))
        colors = ", ".join(p.get("colors", []))
        sku = p.get("sku", "N/A")
        lines.append(f"- {name} (SKU: {sku}, {price} грн). Розміри: {sizes}. Кольори: {colors}")

    return "\n".join(lines)


def _load_vision_guide() -> str:
    """Load and format vision_guide.json for prompt injection."""
    import json
    from pathlib import Path

    # Path: src/agents/pydantic/vision_agent.py → data/vision_guide.json
    # Go up 4 levels: pydantic → agents → src → project_root → data
    guide_path = Path(__file__).parent.parent.parent.parent / "data" / "vision_guide.json"

    try:
        with open(guide_path, encoding="utf-8") as f:
            guide = json.load(f)

        products = guide.get("visual_recognition_guide", {}).get("products", {})
        detection_rules = guide.get("visual_recognition_guide", {}).get("detection_rules", {})

        lines = ["# VISION GUIDE — Детальні ознаки кожного товару\n"]

        for sku, data in products.items():
            name = data.get("name", "Unknown")
            tips = data.get("recognition_tips", [])
            features = data.get("key_features", {})

            lines.append(f"## {name} (SKU: {sku})")
            lines.append(f"- **Верх**: {features.get('top_style', features.get('silhouette', 'N/A'))}")
            lines.append(f"- **Низ**: {features.get('bottom_style', features.get('pants_style', 'N/A'))}")
            lines.append(f"- **Тканина**: {features.get('material', features.get('fabric_texture', 'N/A'))}")
            lines.append(f"- **Вид ззаду**: {features.get('back_view', 'N/A')}")
            lines.append("- **Як розпізнати**:")
            for tip in tips[:3]:  # Top 3 tips
                lines.append(f"  - {tip}")
            lines.append("")

        # Add detection rules summary
        lines.append("# DETECTION RULES (швидкий пошук)")
        lines.append("## По текстурі:")
        for texture, models in detection_rules.get("by_texture", {}).items():
            lines.append(f"- {texture}: {', '.join(models)}")
        lines.append("## По застібці:")
        for closure, models in detection_rules.get("by_closure", {}).items():
            lines.append(f"- {closure}: {', '.join(models)}")

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to load vision_guide.json: %s", e)
        return ""


def _get_vision_prompt() -> str:
    """
    Build comprehensive vision prompt with ALL available context:

    1. Main recognition algorithm (vision_main.md)
    2. Model rules database (model_rules.yaml)
    3. Vision guide with detailed features (vision_guide.json) ← NEW!
    4. Quick reference table for common confusions
    """
    parts = []

    # 1. Load main vision prompt (algorithm)
    try:
        vision_main = registry.get("vision.main").content
        parts.append(vision_main)
    except Exception as e:
        logger.error("Failed to load vision.main: %s", e)
        parts.append("# Vision Agent\nАналізуй фото та знаходь товари MIRT.")

    # 2. Load model rules (database)
    try:
        model_rules = registry.get("vision.model_rules").content
        parts.append("\n---\n# MODEL DATABASE\n")
        parts.append(model_rules)
    except Exception as e:
        logger.warning("Model rules not loaded: %s", e)

    # 3. Load vision guide (detailed features per product) ← NEW!
    vision_guide = _load_vision_guide()
    if vision_guide:
        parts.append("\n---\n")
        parts.append(vision_guide)

    # 4. Add quick confusion prevention table
    parts.append("""
---
# QUICK CONFUSION PREVENTION

| Якщо бачиш... | Це НЕ... | Це... | Чому? |
|---------------|----------|-------|-------|
| Коротку блискавку (half-zip) | Лагуна | МРІЯ | Лагуна = повна |
| Повну блискавку + стоячий комір | Мрія | ЛАГУНА | Мрія = half-zip |
| Капюшон + бавовна | Каприз | РИТМ | Каприз = без капюшона |
| Palazzo + без капюшона | Ритм | КАПРИЗ | Ритм = з капюшоном |
| Лампаси на штанах | Ритм/Каприз | МЕРЕЯ | Тільки Мерея з лампасами |
| Смужка на блузі | Каприз | ВАЛЕРІ | Валері = смужка |
| Блискуча тканина + пояс | Костюм | ТРЕНЧ | Екошкіра блищить |

ВАЖЛИВО:
- Якщо фото зі спини — шукай back_view ознаки!
- Якщо скріншот — шукай текстуру та силует!
- ЗАВЖДИ виклич search_products() для підтвердження!
""")

    return "\n".join(parts)


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
            system_prompt=_get_vision_prompt(),
            retries=2,
        )
        _vision_agent.system_prompt(_add_image_url)
        _vision_agent.tool(name="search_products")(_search_products)
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
