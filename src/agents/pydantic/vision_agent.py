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
from pydantic_ai.models.openai import OpenAIChatModel
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


def _build_model() -> OpenAIChatModel:
    """Build OpenAI model."""
    if settings.LLM_PROVIDER == "openai":
        api_key = settings.OPENAI_API_KEY.get_secret_value()
        base_url = "https://api.openai.com/v1"
        model_name = settings.LLM_MODEL_GPT
    else:
        api_key = settings.OPENROUTER_API_KEY.get_secret_value()
        base_url = settings.OPENROUTER_BASE_URL
        model_name = (
            settings.LLM_MODEL_GROK if settings.LLM_PROVIDER == "openrouter" else settings.AI_MODEL
        )

    if not api_key:
        logger.warning("API Key missing for provider %s", settings.LLM_PROVIDER)
        if settings.LLM_PROVIDER == "openai":
            api_key = settings.OPENROUTER_API_KEY.get_secret_value()
            base_url = settings.OPENROUTER_BASE_URL
            model_name = settings.AI_MODEL

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    provider = OpenAIProvider(openai_client=client)
    return OpenAIChatModel(model_name, provider=provider)


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


async def _load_vision_guide_from_db() -> str:
    """
    Load product visual features from Supabase.

    This replaces the static vision_guide.json with real-time DB data.
    Falls back to JSON if DB is unavailable.
    """
    from src.services.catalog_service import CatalogService

    try:
        catalog = CatalogService()
        products = await catalog.get_products_for_vision()

        if not products:
            logger.warning("📦 No products from DB, falling back to JSON")
            return _load_vision_guide_from_json()

        # Log loaded products for debugging
        product_names = [p.get("name", "?") for p in products[:10]]
        logger.info("📦 Loaded %d products from DB: %s...", len(products), product_names)

        lines = ["# VISION GUIDE — Товари з каталогу (LIVE DATA)\n"]

        # Group by base model name (strip color)
        for product in products:
            name = product.get("name", "Unknown")
            sku = product.get("sku") or product.get("id", "N/A")
            # Use 'colors' column (plural) as per actual DB schema
            color = product.get("colors") or product.get("color", "")

            lines.append(f"## {name}")
            lines.append(f"- **SKU**: {sku}")
            if color:
                lines.append(f"- **Колір**: {color}")

            # Visual features from DB columns
            fabric = product.get("fabric_type")
            if fabric:
                lines.append(f"- **Тканина**: {fabric}")

            closure = product.get("closure_type")
            if closure:
                closure_map = {
                    "half_zip": "half-zip (коротка блискавка)",
                    "full_zip": "повна блискавка",
                    "no_zip": "без блискавки",
                    "buttons": "гудзики",
                }
                lines.append(f"- **Застібка**: {closure_map.get(closure, closure)}")

            if product.get("has_hood"):
                lines.append("- **Капюшон**: ТАК")
            elif product.get("has_hood") is False:
                lines.append("- **Капюшон**: НІ")

            pants = product.get("pants_style")
            if pants:
                pants_map = {
                    "joggers": "джогери (звужені)",
                    "palazzo": "palazzo (широкі)",
                    "classic": "класичні",
                }
                lines.append(f"- **Штани**: {pants_map.get(pants, pants)}")

            back_view = product.get("back_view_description")
            if back_view:
                lines.append(f"- **Вид ззаду**: {back_view}")

            # Recognition tips
            tips = product.get("recognition_tips", [])
            if tips:
                lines.append("- **Як розпізнати**:")
                for tip in tips[:3]:
                    lines.append(f"  - {tip}")

            # Confusion prevention
            confused = product.get("confused_with", [])
            if confused:
                lines.append(f"- **Не плутай з**: {', '.join(confused)}")

            # Price (always useful)
            price = product.get("price")
            if price:
                lines.append(f"- **Ціна**: {price} грн")

            lines.append("")

        # Add detection rules summary
        lines.append(_build_detection_rules_from_products(products))

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to load from DB: %s, falling back to JSON", e)
        return _load_vision_guide_from_json()


def _build_detection_rules_from_products(products: list[dict]) -> str:
    """Build detection rules summary from products."""
    by_fabric: dict[str, list[str]] = {}
    by_closure: dict[str, list[str]] = {}
    by_hood: dict[str, list[str]] = {"з капюшоном": [], "без капюшона": []}

    for p in products:
        name = p.get("name", "Unknown")
        # Extract base name (remove color)
        base_name = name.split("(")[0].strip() if "(" in name else name

        fabric = p.get("fabric_type")
        if fabric:
            by_fabric.setdefault(fabric, []).append(base_name)

        closure = p.get("closure_type")
        if closure:
            by_closure.setdefault(closure, []).append(base_name)

        if p.get("has_hood"):
            by_hood["з капюшоном"].append(base_name)
        elif p.get("has_hood") is False:
            by_hood["без капюшона"].append(base_name)

    lines = ["\n# DETECTION RULES (з БД)"]

    if by_fabric:
        lines.append("## По тканині:")
        for fabric, names in by_fabric.items():
            unique = list(set(names))[:5]
            lines.append(f"- {fabric}: {', '.join(unique)}")

    if by_closure:
        lines.append("## По застібці:")
        for closure, names in by_closure.items():
            unique = list(set(names))[:5]
            lines.append(f"- {closure}: {', '.join(unique)}")

    if by_hood["з капюшоном"] or by_hood["без капюшона"]:
        lines.append("## По капюшону:")
        if by_hood["з капюшоном"]:
            unique = list(set(by_hood["з капюшоном"]))[:5]
            lines.append(f"- З капюшоном: {', '.join(unique)}")
        if by_hood["без капюшона"]:
            unique = list(set(by_hood["без капюшона"]))[:5]
            lines.append(f"- Без капюшона: {', '.join(unique)}")

    return "\n".join(lines)


def _load_vision_guide_from_json() -> str:
    """Fallback: Load from static JSON file."""
    import json
    from pathlib import Path

    guide_path = Path(__file__).parent.parent.parent.parent / "data" / "vision_guide.json"

    try:
        with open(guide_path, encoding="utf-8") as f:
            guide = json.load(f)

        products = guide.get("visual_recognition_guide", {}).get("products", {})

        lines = ["# VISION GUIDE (fallback JSON)\n"]

        for sku, data in products.items():
            name = data.get("name", "Unknown")
            tips = data.get("recognition_tips", [])

            lines.append(f"## {name} (SKU: {sku})")
            for tip in tips[:3]:
                lines.append(f"  - {tip}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to load vision_guide.json: %s", e)
        return ""


def _get_base_vision_prompt() -> str:
    """
    Get base vision prompt (algorithm + rules).

    This is the STATIC part loaded at agent init.
    Product data is loaded DYNAMICALLY via @agent.system_prompt.
    """
    parts = []

    # 1. Load main vision prompt (algorithm)
    try:
        vision_main = registry.get("vision.main").content
        parts.append(vision_main)
    except Exception as e:
        logger.error("Failed to load vision.main: %s", e)
        parts.append("# Vision Agent\nАналізуй фото та знаходь товари MIRT.")

    # 2. Load model rules (static decision tree)
    try:
        model_rules = registry.get("vision.model_rules").content
        parts.append("\n---\n# MODEL DATABASE\n")
        parts.append(model_rules)
    except Exception as e:
        logger.warning("Model rules not loaded: %s", e)

    # 3. Add confusion prevention table with CRITICAL rules
    parts.append("""
---
# ⚠️ КРИТИЧНЕ ПРАВИЛО: ЛАГУНА vs МРІЯ

Ці два костюми ДУЖЕ схожі (обидва плюшеві, однакові кольори), але відрізняються ЗАСТІБКОЮ:

| Модель | Застібка | Як виглядає |
|--------|----------|-------------|
| **ЛАГУНА** | ПОВНА блискавка (від горла до низу) | Блискавка йде через ВЕСЬ перед куртки |
| **МРІЯ** | HALF-ZIP (тільки до грудей) | Блискавка коротка, зверху 15-20 см |

🔍 АЛГОРИТМ ВИЗНАЧЕННЯ:
1. Подивись на блискавку
2. Якщо блискавка йде ДО НИЗУ куртки = ЛАГУНА
3. Якщо блискавка коротка (тільки зверху) = МРІЯ
4. Якщо не видно блискавку — запитай клієнта!

---
# QUICK CONFUSION PREVENTION

| Якщо бачиш... | Це НЕ... | Це... | Чому? |
|---------------|----------|-------|-------|
| ПОВНУ блискавку до низу | Мрія | **ЛАГУНА** | Мрія = half-zip |
| Коротку блискавку (half-zip) | Лагуна | **МРІЯ** | Лагуна = повна |
| Капюшон + бавовна | Каприз | **РИТМ** | Каприз = без капюшона |
| Palazzo + без капюшона | Ритм | **КАПРИЗ** | Ритм = з капюшоном |
| Лампаси на штанах | Ритм/Каприз | **МЕРЕЯ** | Тільки Мерея з лампасами |
| Смужка на блузі | Каприз | **ВАЛЕРІ** | Валері = смужка |
| Блискуча тканина + пояс | Костюм | **ТРЕНЧ** | Екошкіра блищить |

ВАЖЛИВО:
- Якщо фото зі спини — шукай back_view ознаки!
- Якщо скріншот — шукай текстуру та силует!
- ЗАВЖДИ виклич search_products() для підтвердження!
- ЗАВЖДИ ВИЗНАЧАЙ ТОВАР! НЕ СУМНІВАЙСЯ! Слідуй vision_guide!

---
# ⚡ КРИТИЧНО: ЗАВЖДИ ЗАПОВНЮЙ identified_product!

Якщо ти ВПІЗНАВ товар на фото (confidence >= 0.5), ТИ ЗОБОВ'ЯЗАНИЙ заповнити:

```json
{
  "identified_product": {
    "name": "Костюм Лагуна (жовтий)",  // ОБОВ'ЯЗКОВО!
    "price": 0,  // 0 = ціна буде дістана з БД
    "color": "жовтий"  // якщо видно колір
  },
  "confidence": 0.9,
  "reply_to_user": "Це наш Костюм Лагуна! Ціна залежить від розміру..."
}
```

❌ НЕ ПОВЕРТАЙ identified_product = null якщо ти впізнав товар!
❌ НЕ ЧЕКАЙ поки дізнаєшся точну ціну — постав 0!
✅ ГОЛОВНЕ — вкажи name ТОЧНО як в каталозі!
""")

    return "\n".join(parts)


async def _add_live_catalog_context(ctx: RunContext[AgentDeps]) -> str:
    """
    DYNAMIC system prompt: Load fresh product data from DB.

    Called on EACH request, so prices/stock are always current.
    ALWAYS adds recognition tips from JSON for better identification.
    """
    parts = []

    # 1. Load product prices/names from DB
    try:
        vision_guide = await _load_vision_guide_from_db()
        if vision_guide:
            parts.append(f"\n---\n{vision_guide}")
    except Exception as e:
        logger.warning("Failed to load live catalog: %s", e)
        # Fallback to static JSON for product list
        parts.append(f"\n---\n{_load_vision_guide_from_json()}")
        return "\n".join(parts)

    # 2. ALWAYS add detailed recognition tips from JSON (critical for identification!)
    recognition_tips = _load_recognition_tips_from_json()
    if recognition_tips:
        parts.append(f"\n---\n{recognition_tips}")

    return "\n".join(parts)


def _load_recognition_tips_from_json() -> str:
    """Load detailed recognition tips from JSON file (used ALWAYS, not just fallback)."""
    import json
    from pathlib import Path

    guide_path = Path(__file__).parent.parent.parent.parent / "data" / "vision_guide.json"

    try:
        with open(guide_path, encoding="utf-8") as f:
            guide = json.load(f)

        data = guide.get("visual_recognition_guide", {})
        products = data.get("products", {})
        detection_rules = data.get("detection_rules", {})

        lines = ["# ДЕТАЛЬНІ ОЗНАКИ ДЛЯ РОЗПІЗНАВАННЯ\n"]

        # Add key features and tips for each product
        for _sku, product_data in products.items():
            name = product_data.get("name", "Unknown")
            key_features = product_data.get("key_features", {})
            tips = product_data.get("recognition_tips", [])

            lines.append(f"## {name}")

            # Key distinguishing features
            if key_features.get("top_style"):
                lines.append(f"- **Верх**: {key_features['top_style']}")
            if key_features.get("zip_detail"):
                lines.append(f"- **Застібка**: {key_features['zip_detail']}")
            if key_features.get("material"):
                lines.append(f"- **Матеріал**: {key_features['material']}")
            if key_features.get("bottom_style"):
                lines.append(f"- **Штани**: {key_features['bottom_style']}")

            # Recognition tips
            if tips:
                lines.append("- **ЯК РОЗПІЗНАТИ**:")
                for tip in tips[:4]:
                    lines.append(f"  - {tip}")
            lines.append("")

        # Add detection rules
        lines.append("\n# ПРАВИЛА ШВИДКОГО ВИЗНАЧЕННЯ")

        by_closure = detection_rules.get("by_closure", {})
        if by_closure:
            lines.append("\n**По застібці:**")
            for closure_type, models in by_closure.items():
                lines.append(f"- {closure_type}: {', '.join(models)}")

        by_texture = detection_rules.get("by_texture", {})
        if by_texture:
            lines.append("\n**По текстурі:**")
            for texture, models in by_texture.items():
                lines.append(f"- {texture}: {', '.join(models)}")

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to load recognition tips from JSON: %s", e)
        return ""


_vision_agent: Agent[AgentDeps, VisionResponse] | None = None


async def _add_image_url(ctx: RunContext[AgentDeps]) -> str:
    """Add image URL to prompt."""
    if ctx.deps.image_url:
        return f"\n[IMAGE_URL: {ctx.deps.image_url}]"
    return ""


def get_vision_agent() -> Agent[AgentDeps, VisionResponse]:
    """
    Get or create vision agent (lazy initialization).

    Architecture:
    - Base prompt: Static algorithm + rules (loaded once)
    - Dynamic prompt: Live catalog data from DB (loaded per request)
    - Image URL: Added per request
    - Model settings: temperature=0.1 (low for deterministic), reasoning=medium
    """
    global _vision_agent
    if _vision_agent is None:
        # Model settings for vision: low temperature for consistency, medium reasoning
        model_settings = {
            "temperature": 0.1,  # Low temperature = more deterministic = follows rules better
        }
        # Add reasoning effort if supported by model (OpenAI o1/o3, Grok)
        if settings.LLM_REASONING_EFFORT and settings.LLM_REASONING_EFFORT != "none":
            model_settings["reasoning_effort"] = settings.LLM_REASONING_EFFORT

        _vision_agent = Agent(  # type: ignore[call-overload]
            _build_model(),
            deps_type=AgentDeps,
            output_type=VisionResponse,  # PydanticAI 1.23+
            system_prompt=_get_base_vision_prompt(),
            retries=2,
            model_settings=model_settings,  # ← CRITICAL: temperature + reasoning!
        )
        # Dynamic prompts (called on each request)
        _vision_agent.system_prompt(_add_live_catalog_context)  # ← LIVE DB DATA!
        _vision_agent.system_prompt(_add_image_url)

        # Tools
        _vision_agent.tool(name="search_products")(_search_products)

        logger.info(
            "👁️ Vision agent initialized: model=%s, temperature=%.1f, reasoning=%s",
            settings.active_llm_model,
            model_settings.get("temperature", 0.3),
            model_settings.get("reasoning_effort", "none"),
        )

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

    logger.info(
        "👁️ Vision agent starting: image_url=%s", deps.image_url[:50] if deps.image_url else "<none>"
    )

    try:
        result = await asyncio.wait_for(
            agent.run(message, deps=deps, message_history=message_history),
            timeout=120,  # Increased for slow API tiers
        )
        response = result.output  # output_type param, result.output attr

        # Log identified product
        logger.info(
            "👁️ Vision result: product='%s', confidence=%.2f, needs_clarification=%s",
            response.identified_product.name if response.identified_product else "<none>",
            response.confidence,
            response.needs_clarification,
        )
        return response

    except Exception as e:
        logger.exception("👁️ Vision agent error: %s", e)
        return VisionResponse(
            reply_to_user="Вибачте, не вдалося проаналізувати фото. Спробуйте надіслати ще раз 🤍",
            confidence=0.0,
            needs_clarification=True,
            clarification_question="Чи можете надіслати фото ще раз або описати товар?",
        )
