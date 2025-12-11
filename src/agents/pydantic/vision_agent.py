"""
Vision Agent - Photo analysis specialist.
==========================================
Handles photo identification and product matching.
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, ImageUrl, RunContext
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
    """Build OpenAI-compatible model for VISION (multimodal).
    
    IMPORTANT: Uses LLM_MODEL_VISION which MUST be a vision-capable model!
    - OpenAI: gpt-5.1, gpt-4o, gpt-4-vision-preview
    - OpenRouter: x-ai/grok-2-vision-1212, openai/gpt-4o
    """
    model_name = settings.LLM_MODEL_VISION  # MUST be vision-capable!
    
    # Detect if model is OpenAI native (gpt-*) or OpenRouter (provider/model)
    is_openai_model = model_name.startswith("gpt-") or model_name.startswith("o1") or model_name.startswith("o3")
    
    if is_openai_model:
        # Use OpenAI directly
        api_key = settings.OPENAI_API_KEY.get_secret_value()
        base_url = "https://api.openai.com/v1"
        if not api_key:
            # Fallback to OpenRouter for OpenAI models
            api_key = settings.OPENROUTER_API_KEY.get_secret_value()
            base_url = settings.OPENROUTER_BASE_URL
            model_name = f"openai/{model_name}"  # OpenRouter format
            logger.info("Vision using OpenRouter for %s (OPENAI_API_KEY missing)", model_name)
    else:
        # Use OpenRouter for other models (x-ai/*, anthropic/*, etc.)
        api_key = settings.OPENROUTER_API_KEY.get_secret_value()
        base_url = settings.OPENROUTER_BASE_URL

    if not api_key:
        logger.error("❌ No API key for vision model! Set OPENAI_API_KEY or OPENROUTER_API_KEY.")
        raise ValueError(
            "Vision model requires API key. Set OPENAI_API_KEY or OPENROUTER_API_KEY."
        )

    logger.info("👁️ Vision model: %s (via %s)", model_name, base_url[:30])

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


def _load_model_rules_yaml() -> str:
    """Load model rules from generated YAML file."""
    from pathlib import Path

    import yaml

    rules_path = Path(__file__).parent.parent.parent.parent / "data" / "vision" / "generated" / "model_rules.yaml"

    try:
        with open(rules_path, encoding="utf-8") as f:
            rules = yaml.safe_load(f)

        if not rules:
            return ""

        lines = []

        # Add MODEL_RULES section
        model_rules = rules.get("MODEL_RULES", {})
        for name, data in model_rules.items():
            lines.append(f"## {name}")
            lines.append(f"- **Категорія**: {data.get('category', '?')}")
            lines.append(f"- **Тканина**: {data.get('fabric_type', '?')}")
            lines.append(f"- **Ціна**: {data.get('price', '?')} грн")

            markers = data.get("visual_markers", [])
            if markers:
                lines.append("- **Візуальні ознаки**:")
                for m in markers:
                    lines.append(f"  - {m}")

            identify = data.get("identify_by")
            if identify:
                lines.append(f"- **ГОЛОВНА ОЗНАКА**: {identify}")

            confused = data.get("confused_with", [])
            if confused:
                lines.append(f"- **Не плутай з**: {', '.join(confused)}")
                if data.get("how_to_distinguish"):
                    lines.append(f"- **Як відрізнити**: {data['how_to_distinguish'].strip()}")
                if data.get("critical_check"):
                    lines.append(f"- **⚠️ КРИТИЧНА ПЕРЕВІРКА**: {data['critical_check'].strip()}")

            colors = data.get("colors", [])
            if colors:
                lines.append(f"- **Кольори**: {', '.join(colors)}")

            lines.append("")

        # Add DECISION_TREE
        decision_tree = rules.get("DECISION_TREE", "")
        if decision_tree:
            lines.append("# DECISION TREE")
            lines.append(decision_tree)

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to load model_rules.yaml: %s", e)
        return ""


def _load_vision_guide_from_json() -> str:
    """Fallback: Load from static JSON file."""
    import json
    from pathlib import Path

    guide_path = Path(__file__).parent.parent.parent.parent / "data" / "vision" / "generated" / "vision_guide.json"

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

    # 2. Load model rules from generated file (auto-updated from products_master.yaml)
    try:
        model_rules = _load_model_rules_yaml()
        if model_rules:
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
# 🎨 КРИТИЧНО: РОЗРІЗНЯЙ КОЛЬОРИ!

**ПОМАРАНЧЕВИЙ ≠ ЖОВТИЙ!** Це РІЗНІ кольори!

| Колір | Як виглядає | НЕ ПЛУТАЙ з |
|-------|-------------|-------------|
| **ПОМАРАНЧЕВИЙ** | Яскравий, теплий, як апельсин 🍊 | жовтий |
| **ЖОВТИЙ** | Світлий, лимонний, холодний 🍋 | помаранчевий |
| **РОЖЕВИЙ** | Ніжний, пудровий | сірий |
| **СІРИЙ** | Нейтральний, без кольору | рожевий |

⚠️ ЯКЩО БАЧИШ ТЕПЛИЙ ЯСКРАВИЙ КОЛІР = ПОМАРАНЧЕВИЙ!
⚠️ ЯКЩО БАЧИШ СВІТЛИЙ ХОЛОДНИЙ КОЛІР = ЖОВТИЙ!

---
# ⚡ КРИТИЧНО: ЗАВЖДИ ЗАПОВНЮЙ identified_product!

Якщо ти ВПІЗНАВ товар на фото (confidence >= 0.5), ТИ ЗОБОВ'ЯЗАНИЙ заповнити:

```json
{
  "identified_product": {
    "name": "Костюм Лагуна (помаранчевий)",  // ОБОВ'ЯЗКОВО! ВИЗНАЧ КОЛІР З ФОТО!
    "price": 0,  // 0 = ціна буде дістана з БД
    "color": "помаранчевий"  // ВИЗНАЧ З ФОТО! помаранчевий/жовтий/рожевий/сірий
  },
  "confidence": 0.9,
  "reply_to_user": "Це наш Костюм Лагуна!"
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

    guide_path = Path(__file__).parent.parent.parent.parent / "data" / "vision" / "generated" / "vision_guide.json"

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
            distinction = product_data.get("distinction", {})
            recognition_by_angle = product_data.get("recognition_by_angle", {})

            lines.append(f"## {name}")

            # Fabric type (CRITICAL for plush vs cotton vs leather)
            fabric = key_features.get("fabric")
            if fabric:
                lines.append(f"- **ТКАНИНА**: {fabric}")

            # Visual markers (CRITICAL)
            markers = key_features.get("markers", [])
            if markers:
                lines.append("- **КЛЮЧОВІ ОЗНАКИ**:")
                for marker in markers:
                    lines.append(f"  - {marker}")

            # Recognition by angle
            if recognition_by_angle:
                front = recognition_by_angle.get("front")
                if front:
                    lines.append(f"- **Вид спереду**: {front}")
                detail = recognition_by_angle.get("detail")
                if detail:
                    lines.append(f"- **Деталь**: {detail}")

            # Texture description
            texture = product_data.get("texture_description")
            if texture:
                lines.append(f"- **Текстура**: {texture}")

            # CRITICAL: Distinction from similar products
            confused_with = distinction.get("confused_with", [])
            if confused_with:
                lines.append(f"- **⚠️ НЕ ПЛУТАЙ З**: {', '.join(confused_with)}")
                how = distinction.get("how_to_distinguish")
                if how:
                    lines.append(f"- **ЯК ВІДРІЗНИТИ**: {how.strip()}")
                critical = distinction.get("critical_check")
                if critical:
                    lines.append(f"- **🔍 КРИТИЧНА ПЕРЕВІРКА**: {critical.strip()}")

            # Unique identifier
            unique = distinction.get("unique_identifier")
            if unique:
                lines.append(f"- **УНІКАЛЬНА ОЗНАКА**: {unique}")

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
            "temperature": 0.3,  # Moderate temp for better color recognition
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

    # Build MULTIMODAL input: [text, ImageUrl]
    # PydanticAI requires ImageUrl for vision models to actually SEE the image!
    if deps.image_url:
        # Multimodal input: list of content parts
        user_input: list[str | ImageUrl] = [
            message or "Аналізуй це фото та знайди товар MIRT.",
            ImageUrl(url=deps.image_url),
        ]
        logger.info(
            "👁️ Vision agent starting (MULTIMODAL): image_url=%s",
            deps.image_url[:80] if deps.image_url else "<none>",
        )
    else:
        # No image - cannot proceed with vision analysis
        logger.error("👁️ Vision agent called WITHOUT image! deps.image_url is empty.")
        return VisionResponse(
            reply_to_user="Надішліть фото товару, будь ласка 📷",
            confidence=0.0,
            needs_clarification=True,
            clarification_question="Чи можете надіслати фото товару?",
        )

    try:
        result = await asyncio.wait_for(
            agent.run(user_input, deps=deps, message_history=message_history),
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
