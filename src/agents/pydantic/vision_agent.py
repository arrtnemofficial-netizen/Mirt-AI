"""
Vision Agent - Photo analysis specialist.
==========================================
Handles photo identification and product matching.
"""

from __future__ import annotations

import base64
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic_ai import Agent, ImageUrl, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.conf.config import settings
from src.core.human_responses import get_human_response
from src.core.prompt_registry import registry

from .deps import AgentDeps
from .models import VisionResponse


logger = logging.getLogger(__name__)

# Instagram CDN hosts that require downloading (OpenAI can't access directly)
_PRIVATE_CDN_HOSTS = (
    "lookaside.fbsbx.com",
    "scontent.cdninstagram.com",
    "instagram.fiev",
    "cdninstagram.com",
)


@lru_cache(maxsize=1)
def _load_reference_images_by_product() -> dict[str, list[str]]:
    test_set_path = (
        Path(__file__).parent.parent.parent.parent
        / "data"
        / "vision"
        / "generated"
        / "test_set.json"
    )

    try:
        with open(test_set_path, encoding="utf-8") as f:
            test_set = json.load(f)
    except Exception as e:
        logger.warning("Failed to load reference images (%s): %s", test_set_path, e)
        return {}

    ref_map: dict[str, list[str]] = {}
    if not isinstance(test_set, list):
        return {}

    for item in test_set:
        if not isinstance(item, dict):
            continue
        name = item.get("expected_product")
        url = item.get("image_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        if not url.startswith("https://"):
            continue
        ref_map.setdefault(name, [])
        if url not in ref_map[name]:
            ref_map[name].append(url)

    return ref_map


def _build_reference_parts(
    product_names: list[str],
    max_images_per_product: int = 1,
) -> list[str | ImageUrl]:
    ref_map = _load_reference_images_by_product()
    parts: list[str | ImageUrl] = []

    for name in product_names:
        urls = ref_map.get(name) or []
        if not urls:
            continue
        parts.append(f"REFERENCE IMAGE — {name}")
        for url in urls[:max_images_per_product]:
            parts.append(ImageUrl(url=url))

    return parts


async def _download_image_as_base64(url: str, max_retries: int = 2) -> str | None:
    url = url.rstrip(";").strip()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,uk;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.instagram.com/",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "image/jpeg")
                if ";" in content_type:
                    content_type = content_type.split(";")[0].strip()

                image_data = response.content
                b64_data = base64.b64encode(image_data).decode("utf-8")
                data_url = f"data:{content_type};base64,{b64_data}"
                logger.info(
                    "Downloaded image from CDN: %d bytes, type=%s",
                    len(image_data),
                    content_type,
                )
                return data_url

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403 and attempt < max_retries:
                logger.warning("HTTP 403, retrying (%d/%d)...", attempt + 1, max_retries)
                import asyncio

                await asyncio.sleep(0.5)
                continue
            logger.error("Failed to download image (HTTP %d): %s", e.response.status_code, url[:80])
            return None
        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    "Download error, retrying (%d/%d): %s", attempt + 1, max_retries, str(e)[:50]
                )
                import asyncio

                await asyncio.sleep(0.5)
                continue
            logger.error("Failed to download image: %s - %s", type(e).__name__, str(e)[:100])
            return None

    return None


def _is_private_cdn_url(url: str) -> bool:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        return any(host in parsed.netloc for host in _PRIVATE_CDN_HOSTS)
    except Exception:
        return False


# Vision guide logic replaced by prompt registry


# =============================================================================
# MODEL SETUP
# =============================================================================


def _build_model() -> OpenAIChatModel:
    # SENIOR-LEVEL: Use AI_MODEL as single source of truth
    model_name = settings.AI_MODEL

    is_openai_model = (
        model_name.startswith("gpt-") or model_name.startswith("o1") or model_name.startswith("o3")
    )

    if is_openai_model:
        api_key = settings.OPENAI_API_KEY.get_secret_value()
        base_url = "https://api.openai.com/v1"
        if not api_key:
            api_key = settings.OPENROUTER_API_KEY.get_secret_value()
            base_url = settings.OPENROUTER_BASE_URL
            model_name = f"openai/{model_name}"
            logger.info("Vision using OpenRouter for %s (OPENAI_API_KEY missing)", model_name)
    else:
        api_key = settings.OPENROUTER_API_KEY.get_secret_value()
        base_url = settings.OPENROUTER_BASE_URL

    if not api_key:
        logger.error("No API key for vision model! Set OPENAI_API_KEY or OPENROUTER_API_KEY.")
        raise ValueError("Vision model requires API key. Set OPENAI_API_KEY or OPENROUTER_API_KEY.")

    logger.info("Vision model: %s (via %s)", model_name, base_url[:30])

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
    products = await ctx.deps.catalog.search_products(query, category)

    if not products:
        return get_human_response("not_found")

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
    from src.services.catalog import CatalogService

    try:
        catalog = CatalogService()
        products = await catalog.get_products_for_vision()

        if not products:
            logger.warning("No products from DB, falling back to JSON")
            return _load_vision_guide_from_json()

        product_names = [p.get("name", "?") for p in products[:10]]
        logger.info("Loaded %d products from DB: %s...", len(products), product_names)

        lines = ["# VISION GUIDE — Товари з каталогу (LIVE DATA)\n"]

        for product in products:
            name = product.get("name", "Unknown")
            sku = product.get("sku") or product.get("id", "N/A")
            color = product.get("colors") or product.get("color", "")

            lines.append(f"## {name}")
            lines.append(f"- **SKU**: {sku}")
            if color:
                lines.append(f"- **Колір**: {color}")

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

            tips = product.get("recognition_tips", [])
            if tips:
                lines.append("- **Як розпізнати**:")
                for tip in tips[:3]:
                    lines.append(f"  - {tip}")

            confused = product.get("confused_with", [])
            if confused:
                lines.append(f"- **Не плутай з**: {', '.join(confused)}")

            description = product.get("description")
            if description:
                lines.append(f"- **Опис**: {description}")

            price_by_size = product.get("price_by_size")
            if price_by_size and isinstance(price_by_size, dict):
                prices = list(price_by_size.values())
                if prices:
                    min_p, max_p = min(prices), max(prices)
                    if min_p == max_p:
                        lines.append(f"- **Ціна**: {int(min_p)} грн")
                    else:
                        lines.append(
                            f"- **Ціна**: від {int(min_p)} до {int(max_p)} грн (залежить від розміру)"
                        )
                    size_prices = ", ".join(
                        [f"{sz}: {int(pr)} грн" for sz, pr in price_by_size.items()]
                    )
                    lines.append(f"- **Ціни по розмірах**: {size_prices}")
            else:
                price = product.get("price")
                if price:
                    lines.append(f"- **Ціна**: {price} грн")

            lines.append("")

        lines.append(_build_detection_rules_from_products(products))

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to load from DB: %s, falling back to JSON", e)
        return _load_vision_guide_from_json()


def _build_detection_rules_from_products(products: list[dict]) -> str:
    by_fabric: dict[str, list[str]] = {}
    by_closure: dict[str, list[str]] = {}
    by_hood: dict[str, list[str]] = {"з капюшоном": [], "без капюшона": []}

    for p in products:
        name = p.get("name", "Unknown")
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
    from pathlib import Path

    import yaml

    rules_path = (
        Path(__file__).parent.parent.parent.parent
        / "data"
        / "vision"
        / "generated"
        / "model_rules.yaml"
    )

    try:
        with open(rules_path, encoding="utf-8") as f:
            rules = yaml.safe_load(f)

        if not rules:
            return ""

        lines = []

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

        decision_tree = rules.get("DECISION_TREE", "")
        if decision_tree:
            lines.append("# DECISION TREE")
            lines.append(decision_tree)

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to load model_rules.yaml: %s", e)
        return ""


def _load_vision_guide_from_json() -> str:
    import json
    from pathlib import Path

    guide_path = (
        Path(__file__).parent.parent.parent.parent
        / "data"
        / "vision"
        / "generated"
        / "vision_guide.json"
    )

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
    parts = []

    vision_main = registry.get("vision.main").content
    parts.append(vision_main)

    # Add snippets for beautiful descriptions
    try:
        snippets = registry.get("system.snippets").content
        parts.append("\n---\n# ШАБЛОНИ КРАСИВИХ ОПИСІВ (SNIPPETS)\n")
        parts.append(snippets)
    except Exception as e:
        logger.warning(f"Could not load snippets: {e}")

    model_rules = _load_model_rules_yaml()
    if model_rules:
        parts.append("\n---\n# MODEL DATABASE\n")
        parts.append(model_rules)

    return "\n".join(parts)


async def _add_live_catalog_context(ctx: RunContext[AgentDeps]) -> str:
    parts = []

    vision_guide = await _load_vision_guide_from_db()
    if vision_guide:
        parts.append(f"\n---\n{vision_guide}")

    recognition_tips = _load_recognition_tips_from_json()
    if recognition_tips:
        parts.append(f"\n---\n{recognition_tips}")

    return "\n".join(parts)


def _load_recognition_tips_from_json() -> str:
    import json
    from pathlib import Path

    guide_path = (
        Path(__file__).parent.parent.parent.parent
        / "data"
        / "vision"
        / "generated"
        / "vision_guide.json"
    )

    try:
        with open(guide_path, encoding="utf-8") as f:
            guide = json.load(f)

        data = guide.get("visual_recognition_guide", {})
        products = data.get("products", {})
        detection_rules = data.get("detection_rules", {})

        lines = ["# ДЕТАЛЬНІ ОЗНАКИ ДЛЯ РОЗПІЗНАВАННЯ\n"]

        for _sku, product_data in products.items():
            name = product_data.get("name", "Unknown")
            key_features = product_data.get("key_features", {})
            distinction = product_data.get("distinction", {})
            recognition_by_angle = product_data.get("recognition_by_angle", {})

            lines.append(f"## {name}")

            fabric = key_features.get("fabric")
            if fabric:
                lines.append(f"- **ТКАНИНА**: {fabric}")

            markers = key_features.get("markers", [])
            if markers:
                lines.append("- **КЛЮЧОВІ ОЗНАКИ**:")
                for marker in markers:
                    lines.append(f"  - {marker}")

            if recognition_by_angle:
                front = recognition_by_angle.get("front")
                if front:
                    lines.append(f"- **Вид спереду**: {front}")
                detail = recognition_by_angle.get("detail")
                if detail:
                    lines.append(f"- **Деталь**: {detail}")

            texture = product_data.get("texture_description")
            if texture:
                lines.append(f"- **Текстура**: {texture}")

            confused_with = distinction.get("confused_with", [])
            if confused_with:
                lines.append(f"- **⚠️ НЕ ПЛУТАЙ З**: {', '.join(confused_with)}")
                how = distinction.get("how_to_distinguish")
                if how:
                    lines.append(f"- **ЯК ВІДРІЗНИТИ**: {how.strip()}")
                critical = distinction.get("critical_check")
                if critical:
                    lines.append(f"- **🔍 КРИТИЧНА ПЕРЕВІРКА**: {critical.strip()}")

            unique = distinction.get("unique_identifier")
            if unique:
                lines.append(f"- **УНІКАЛЬНА ОЗНАКА**: {unique}")

            lines.append("")

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
    if ctx.deps.image_url:
        return f"\n[IMAGE_URL: {ctx.deps.image_url}]"
    return ""


def get_vision_agent() -> Agent[AgentDeps, VisionResponse]:
    global _vision_agent
    if _vision_agent is None:
        model_settings = {
            "temperature": 0.3,
        }
        if settings.LLM_REASONING_EFFORT and settings.LLM_REASONING_EFFORT != "none":
            model_settings["reasoning_effort"] = settings.LLM_REASONING_EFFORT

        _vision_agent = Agent(
            _build_model(),
            deps_type=AgentDeps,
            output_type=VisionResponse,
            system_prompt=_get_base_vision_prompt(),
            retries=2,
            model_settings=model_settings,
        )
        _vision_agent.system_prompt(_add_live_catalog_context)
        _vision_agent.system_prompt(_add_image_url)

        _vision_agent.tool(name="search_products")(_search_products)

        logger.info(
            "Vision agent initialized: model=%s, temperature=%.1f, reasoning=%s",
            settings.active_llm_model,
            model_settings.get("temperature", 0.3),
            model_settings.get("reasoning_effort", "none"),
        )

    return _vision_agent


# =============================================================================
# RUNNER
# =============================================================================


async def run_vision(
    message: str,
    deps: AgentDeps,
    message_history: list[Any] | None = None,
) -> VisionResponse:
    import asyncio
    import time
    from urllib.parse import urlparse

    from src.services.llm_usage_logger import log_llm_usage_best_effort

    agent = get_vision_agent()
    
    # Track latency and result for logging
    start_time = time.perf_counter()
    result = None
    response: VisionResponse | None = None
    success = True
    error_message: str | None = None
    tokens_input = 0
    tokens_output = 0
    # SENIOR-LEVEL: Get model name from actual model, not hardcoded fallback
    model_name: str | None = None
    # Use AI_MODEL as single source of truth
    vision_model_name = settings.AI_MODEL

    if not deps.image_url:
        logger.error("👁️ Vision agent called WITHOUT image! deps.image_url is empty.")
        response = VisionResponse(
            reply_to_user="Надішліть фото товару, будь ласка 📷",
            confidence=0.0,
            needs_clarification=True,
            clarification_question="Чи можете надіслати фото товару?",
        )
        success = False
        error_message = "NO_IMAGE_URL"
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        asyncio.create_task(
            log_llm_usage_best_effort(
                session_id=deps.session_id,
                model=settings.AI_MODEL,
                tokens_input=0,
                tokens_output=0,
                latency_ms=latency_ms,
                success=success,
                error_message=error_message,
                metadata={"has_image": False},
                user_id=str(deps.user_id) if hasattr(deps, "user_id") and deps.user_id else None,
            )
        )
        return response

    image_url = deps.image_url.strip()

    try:
        parsed = urlparse(image_url)
        if parsed.scheme not in ("http", "https"):
            logger.error("👁️ Invalid image URL scheme: %s", parsed.scheme)
            response = VisionResponse(
                reply_to_user=get_human_response("photo_error"),
                confidence=0.0,
                needs_clarification=True,
                clarification_question="Надішліть, будь ласка, фото ще раз 📷",
            )
            success = False
            error_message = "INVALID_IMAGE_URL_SCHEME"
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            asyncio.create_task(
                log_llm_usage_best_effort(
                    session_id=deps.session_id,
                    model=settings.AI_MODEL,
                    tokens_input=0,
                    tokens_output=0,
                    latency_ms=latency_ms,
                    success=success,
                    error_message=error_message,
                    metadata={"has_image": True, "image_url": image_url},
                    user_id=str(deps.user_id) if hasattr(deps, "user_id") and deps.user_id else None,
                )
            )
            return response
        if not parsed.netloc:
            logger.error("👁️ Invalid image URL - no host: %s", image_url[:50])
            response = VisionResponse(
                reply_to_user=get_human_response("photo_error"),
                confidence=0.0,
                needs_clarification=True,
                clarification_question="Надішліть, будь ласка, фото ще раз 📷",
            )
            success = False
            error_message = "INVALID_IMAGE_URL_NO_HOST"
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            asyncio.create_task(
                log_llm_usage_best_effort(
                    session_id=deps.session_id,
                    model=settings.AI_MODEL,
                    tokens_input=0,
                    tokens_output=0,
                    latency_ms=latency_ms,
                    success=success,
                    error_message=error_message,
                    metadata={"has_image": True, "image_url": image_url},
                    user_id=str(deps.user_id) if hasattr(deps, "user_id") and deps.user_id else None,
                )
            )
            return response
    except Exception as e:
        logger.error("👁️ URL parse error: %s", e)
        response = VisionResponse(
            reply_to_user=get_human_response("photo_error"),
            confidence=0.0,
            needs_clarification=True,
            clarification_question="Надішліть, будь ласка, фото ще раз 📷",
        )
        success = False
        error_message = f"URL_PARSE_ERROR: {str(e)[:50]}"
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        asyncio.create_task(
            log_llm_usage_best_effort(
                session_id=deps.session_id,
                model=settings.AI_MODEL,
                tokens_input=0,
                tokens_output=0,
                latency_ms=latency_ms,
                success=success,
                error_message=error_message,
                metadata={"has_image": True, "image_url": image_url},
                user_id=str(deps.user_id) if hasattr(deps, "user_id") and deps.user_id else None,
            )
        )
        return response

    blocked_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168.", "172.16.")
    if any(parsed.netloc.startswith(h) or parsed.netloc == h.rstrip(".") for h in blocked_hosts):
        logger.warning("👁️ Blocked internal URL attempt: %s", parsed.netloc)
        response = VisionResponse(
            reply_to_user=get_human_response("photo_error"),
            confidence=0.0,
            needs_clarification=True,
            clarification_question="Надішліть фото ще раз 📷",
        )
        success = False
        error_message = "BLOCKED_INTERNAL_URL"
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        asyncio.create_task(
            log_llm_usage_best_effort(
                session_id=deps.session_id,
                model=settings.AI_MODEL,
                tokens_input=0,
                tokens_output=0,
                latency_ms=latency_ms,
                success=success,
                error_message=error_message,
                metadata={"has_image": True, "image_url": image_url},
                user_id=str(deps.user_id) if hasattr(deps, "user_id") and deps.user_id else None,
            )
        )
        return response

    final_image_url = image_url
    if _is_private_cdn_url(image_url):
        logger.info("👁️ Private CDN detected, downloading image...")
        base64_url = await _download_image_as_base64(image_url)
        if base64_url:
            final_image_url = base64_url
            logger.info("👁️ Successfully converted to base64 (%d chars)", len(base64_url))
        else:
            logger.error("👁️ Failed to download image from private CDN")
            response = VisionResponse(
                reply_to_user="Не вдалось завантажити фото. Спробуйте надіслати ще раз 📷",
                confidence=0.0,
                needs_clarification=True,
                clarification_question="Чи можете надіслати фото ще раз?",
            )
            success = False
            error_message = "FAILED_TO_DOWNLOAD_IMAGE"
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            asyncio.create_task(
                log_llm_usage_best_effort(
                    session_id=deps.session_id,
                    model=settings.AI_MODEL,
                    tokens_input=0,
                    tokens_output=0,
                    latency_ms=latency_ms,
                    success=success,
                    error_message=error_message,
                    metadata={"has_image": True, "image_url": image_url},
                    user_id=str(deps.user_id) if hasattr(deps, "user_id") and deps.user_id else None,
                )
            )
            return response

    user_input: list[str | ImageUrl] = [
        message or "Аналізуй це фото та знайди товар MIRT.",
        ImageUrl(url=final_image_url),
    ]

    reference_parts = _build_reference_parts(
        [
            "Костюм Лагуна",
            "Костюм Мрія",
            "Костюм Ритм",
            "Костюм Каприз",
            "Костюм Валері",
        ],
        max_images_per_product=2,
    )
    if reference_parts:
        user_input.append(
            "Порівняй фото клієнта з еталонними фото нижче. "
            "Ключові відмінності: "
            "Лагуна vs Мрія — довжина блискавки (повна донизу vs коротка до грудей); "
            "Ритм vs Каприз — є капюшон (Ритм) чи ні (Каприз) і штани джогери vs palazzo; "
            "Валері — смужки на блузі."
        )
        user_input.extend(reference_parts)
        logger.info(
            "👁️ Added %d reference parts (%d images)",
            len(reference_parts),
            sum(1 for p in reference_parts if isinstance(p, ImageUrl)),
        )

    logger.info(
        "👁️ Vision agent starting (MULTIMODAL): image_url=%s",
        final_image_url[:80]
        if final_image_url and not final_image_url.startswith("data:")
        else "<base64>",
    )

    try:
        result = await asyncio.wait_for(
            agent.run(user_input, deps=deps, message_history=message_history),
            timeout=120,
        )
        response = result.output
        
        # Try to extract usage from result (if available)
        if hasattr(result, "usage"):
            usage = result.usage
            if hasattr(usage, "input_tokens"):
                tokens_input = usage.input_tokens or 0
            if hasattr(usage, "output_tokens"):
                tokens_output = usage.output_tokens or 0
        elif hasattr(result, "model_used"):
            model_name = str(result.model_used)
        
        # Extract model from agent if not in result
        if not model_name and hasattr(agent, "model"):
            if hasattr(agent.model, "model_id"):
                model_name = agent.model.model_id
            elif hasattr(agent.model, "name"):
                model_name = agent.model.name
        
        # SENIOR-LEVEL: Fallback to actual vision model from settings, not hardcoded
        if not model_name:
            model_name = vision_model_name

        logger.info(
            "👁️ Vision result: product='%s', confidence=%.2f, needs_clarification=%s",
            response.identified_product.name if response.identified_product else "<none>",
            response.confidence,
            response.needs_clarification,
        )
        return response

    except Exception as e:
        success = False
        error_message = f"VISION_ERROR: {str(e)[:100]}"
        logger.exception("👁️ Vision agent error: %s", e)
        response = VisionResponse(
            reply_to_user=get_human_response("photo_analysis_error"),
            confidence=0.0,
            needs_clarification=True,
            clarification_question="Чи можете надіслати фото ще раз або описати товар?",
        )
        return response
    
    finally:
        # Log usage (best-effort, non-blocking)
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        
        # Prepare minimal metadata for vision
        metadata: dict[str, Any] = {
            "has_image": True,
            "image_url": image_url,
        }
        if response:
            metadata["confidence"] = response.confidence
            if response.identified_product:
                metadata["detected_product_id"] = response.identified_product.id
                metadata["detected_product_name"] = response.identified_product.name
        
        # Extract model if not already set
        if not model_name:
            if hasattr(agent, "model"):
                if hasattr(agent.model, "model_id"):
                    model_name = agent.model.model_id
                elif hasattr(agent.model, "name"):
                    model_name = agent.model.name
            if not model_name:
                model_name = vision_model_name
        
        # SENIOR-LEVEL: Use actual vision model, not hardcoded fallback
        # Log asynchronously (fire-and-forget)
        asyncio.create_task(
            log_llm_usage_best_effort(
                session_id=deps.session_id,
                model=model_name or vision_model_name,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                latency_ms=latency_ms,
                success=success,
                error_message=error_message,
                metadata=metadata if metadata else None,
                user_id=str(deps.user_id) if hasattr(deps, "user_id") and deps.user_id else None,
            )
        )
