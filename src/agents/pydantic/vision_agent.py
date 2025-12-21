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
<<<<<<< Updated upstream
from src.core.prompt_loader import get_system_prompt_text
=======
from src.core.human_responses import get_human_response
from src.core.human_responses import get_human_response
from src.core.prompt_registry import registry, get_snippet_by_header
>>>>>>> Stashed changes

from .deps import AgentDeps
from .models import VisionResponse


logger = logging.getLogger(__name__)

# Vision guide path
VISION_GUIDE_PATH = Path(__file__).parent.parent.parent.parent / "data" / "vision_guide.json"


<<<<<<< Updated upstream
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
=======
# Reference logic moved to VisionContextService


def _build_reference_parts(
    ref_map: dict[str, list[str]],
    product_names: list[str],
    max_images_per_product: int = 1,
) -> list[str | ImageUrl]:
    parts: list[str | ImageUrl] = []

    labels_json = get_snippet_by_header("VISION_LABELS")
    labels = json.loads(labels_json[0]) if labels_json else {}
    ref_prefix = labels.get("reference_image_prefix", "REFERENCE IMAGE — ")

    for name in product_names:
        urls = ref_map.get(name) or []
        if not urls:
            continue
        parts.append(f"{ref_prefix}{name}")
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
>>>>>>> Stashed changes


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
<<<<<<< Updated upstream
        return "На жаль, за вашим запитом нічого не знайдено."
        
    lines = ["Знайдені товари:"]
=======
        return get_human_response("not_found")

    lines = [get_snippet_by_header("VISION_NO_PRODUCTS")[0]]
>>>>>>> Stashed changes
    for p in products:
        name = p.get("name")
        price = p.get("price")
        sizes = ", ".join(p.get("sizes", []))
        colors = ", ".join(p.get("colors", []))
        sku = p.get("sku", "N/A")
<<<<<<< Updated upstream
        lines.append(f"- {name} (SKU: {sku}, {price} грн). Розміри: {sizes}. Кольори: {colors}")
        
    return "\n".join(lines)


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
2. Опиши що ти бачиш (колір, тип одягу, деталі)
3. ВИКОРИСТОВУЙ інструмент `search_products` щоб знайти цей товар в базі даних!
   - Шукай за ключовими словами (наприклад "рожева сукня", "костюм мерея")
4. Якщо знайшов товар - поверни його деталі (назву, ціну, ID)
5. Якщо не знайшов - запропонуй схожі

## ФОРМАТ ВІДПОВІДІ:
- Якщо знайшов товар: опиши його, дай ціну, запитай розмір
- Якщо не впевнений: запропонуй схожі варіанти
- Якщо не з каталогу: ввічливо поясни що не маємо такого

## ЗАБОРОНЕНО:
- Вигадувати товари яких немає в результатах пошуку
- Називати ціни "зі стелі"
- Пропонувати кольори/розміри яких немає

Відповідай УКРАЇНСЬКОЮ, тепло як менеджер Ольга 🤍
"""

    # Build final prompt with vision guide
    if vision_guide:
        return f"{vision_instructions}\n---\n# VISION RECOGNITION GUIDE\n{vision_guide}"
    else:
        return vision_instructions
=======
        tmpl = get_snippet_by_header("VISION_PRODUCT_LINE")[0]
        lines.append(tmpl.format(name=name, sku=sku, price=price, sizes=sizes, colors=colors))

    return "\n".join(lines)


def _get_base_vision_prompt() -> str:
    parts = []

    base_identity = registry.get("system.base_identity").content
    parts.append(base_identity)

    vision_main = registry.get("vision.main").content
    parts.append(vision_main)

    # Tone of voice snippets
    try:
        snippets = registry.get("system.snippets").content
        parts.append("\n---\n" + get_snippet_by_header("VISION_SNIPPETS_HEADER")[0] + "\n")
        parts.append(snippets)
    except Exception as e:
        logger.warning(f"Could not load snippets: {e}")

    return "\n".join(parts)


async def _add_vision_context(ctx: RunContext[AgentDeps]) -> str:
    """Inject dynamic vision context (live catalog, rules, tips)."""
    if not ctx.deps.vision:
        return ""
    return await ctx.deps.vision.get_full_context()
>>>>>>> Stashed changes


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
<<<<<<< Updated upstream
=======
        _vision_agent.system_prompt(_add_vision_context)
>>>>>>> Stashed changes
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

<<<<<<< Updated upstream
    # Add image context to message
    if deps.image_url and "[IMAGE_URL:" not in message:
        message = f"{message}\n\n[IMAGE_URL: {deps.image_url}]"
=======
    if not deps.image_url:
        logger.error("👁️ Vision agent called WITHOUT image! deps.image_url is empty.")
        return VisionResponse(
            reply_to_user=get_snippet_by_header("VISION_NO_IMAGE")[0],
            confidence=0.0,
            needs_clarification=True,
            clarification_question=get_snippet_by_header("VISION_ASK_PHOTO")[0],
        )

    image_url = deps.image_url.strip()

    try:
        parsed = urlparse(image_url)
        if parsed.scheme not in ("http", "https"):
            logger.error("👁️ Invalid image URL scheme: %s", parsed.scheme)
            return VisionResponse(
                reply_to_user=get_human_response("photo_error"),
                confidence=0.0,
                needs_clarification=True,
                clarification_question=get_snippet_by_header("VISION_INVALID_URL")[0],
            )
        if not parsed.netloc:
            logger.error("👁️ Invalid image URL - no host: %s", image_url[:50])
            return VisionResponse(
                reply_to_user=get_human_response("photo_error"),
                confidence=0.0,
                needs_clarification=True,
                clarification_question=get_snippet_by_header("VISION_INVALID_URL")[0],
            )
    except Exception as e:
        logger.error("👁️ URL parse error: %s", e)
        return VisionResponse(
            reply_to_user=get_human_response("photo_error"),
            confidence=0.0,
            needs_clarification=True,
            clarification_question=get_snippet_by_header("VISION_INVALID_URL")[0],
        )

    blocked_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168.", "172.16.")
    if any(parsed.netloc.startswith(h) or parsed.netloc == h.rstrip(".") for h in blocked_hosts):
        logger.warning("👁️ Blocked internal URL attempt: %s", parsed.netloc)
        return VisionResponse(
            reply_to_user=get_human_response("photo_error"),
            confidence=0.0,
            needs_clarification=True,
            clarification_question=get_snippet_by_header("VISION_INVALID_URL")[0],
        )

    final_image_url = image_url
    if _is_private_cdn_url(image_url):
        logger.info("👁️ Private CDN detected, downloading image...")
        base64_url = await _download_image_as_base64(image_url)
        if base64_url:
            final_image_url = base64_url
            logger.info("👁️ Successfully converted to base64 (%d chars)", len(base64_url))
        else:
            logger.error("👁️ Failed to download image from private CDN")
            return VisionResponse(
                reply_to_user=get_snippet_by_header("VISION_DOWNLOAD_ERROR")[0],
                confidence=0.0,
                needs_clarification=True,
                clarification_question=get_snippet_by_header("VISION_RETRY_PHOTO")[0],
            )

    labels_json = get_snippet_by_header("VISION_LABELS")
    labels = json.loads(labels_json[0]) if labels_json else {}
    
    user_input: list[str | ImageUrl] = [
        message or labels.get("vision_default_analysis_prompt", "Аналізуй це фото та знайди товар MIRT."),
        ImageUrl(url=final_image_url),
    ]

    model_names = []
    if deps.vision:
        model_names = deps.vision.get_model_names(max_models=5)
    
    reference_parts = []
    if deps.vision and model_names:
        ref_map = deps.vision.get_reference_images_map(model_names)
        reference_parts = _build_reference_parts(
            ref_map,
            model_names,
            max_images_per_product=2,
        )

    if reference_parts:
        ref_instr = get_snippet_by_header("VISION_REFERENCE_INSTRUCTION")
        user_input.append(
            ref_instr[0] if ref_instr else "Use the model database and reference images to disambiguate similar models."
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
>>>>>>> Stashed changes

    try:
        result = await asyncio.wait_for(
            agent.run(message, deps=deps, message_history=message_history),
            timeout=120,  # Increased for slow API tiers
        )
        return result.output  # output_type param, result.output attr

    except Exception as e:
<<<<<<< Updated upstream
        logger.exception("Vision agent error: %s", e)
=======
        logger.exception("👁️ Vision agent error: %s", e)
        clarif = get_snippet_by_header("VISION_ASK_PHOTO")
>>>>>>> Stashed changes
        return VisionResponse(
            reply_to_user="Вибачте, не вдалося проаналізувати фото. Спробуйте надіслати ще раз 🤍",
            confidence=0.0,
            needs_clarification=True,
            clarification_question=clarif[0] if clarif else "Чи можете надіслати фото ще раз або описати товар?",
        )
