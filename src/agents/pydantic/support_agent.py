"""
Support/Sales Agent - Prompts loaded from data/prompts/states/ and data/prompts/system/
=======================================================
MIRT AI AGENT v7.0 - "Софія"

IDENTITY (BLOCK 2):
- role: "AI-консультант магазину дитячого одягу MIRT"
- agent_name: "Софія"
- personality: "Жива людина: можу перепитати, можу чесно сказати, якщо не впевнена."

IMMUTABLE_RULES:
- [P0] Мова відповіді ТІЛЬКИ українська
- [P0] ЗАБОРОНЕНО вигадувати товари, кольори, розміри, ціни - ТІЛЬКИ з CATALOG
- [P0] Максимум 900 символів у відповіді
- [P0] ЗАЛІЗОБЕТОННЕ ПРАВИЛО: На межах (120, 131, 143, 155 см) НЕ переходимо в більший розмір!

OUTPUT_CONTRACT:
- event: simple_answer/clarifying_question/multi_option/escalation/end_smalltalk
- messages: [{type: "text", content: "..."}]
- products: [{id, name, price, size, color, photo_url}] - ТІЛЬКИ з CATALOG!
- metadata: {session_id, current_state, intent, escalation_level}
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.conf.config import settings
from src.conf.payment_config import format_requisites_multiline
from src.core.human_responses import get_human_response
from src.core.prompt_registry import registry

from .deps import AgentDeps
from .models import (
    EscalationInfo,
    MessageItem,
    ResponseMetadata,
    SupportResponse,
)


logger = logging.getLogger(__name__)


def _get_timeout_response() -> str:
    """Get human-like timeout response."""
    return get_human_response("timeout")


def _get_error_response() -> str:
    """Get human-like error response."""
    return get_human_response("error")


# =============================================================================
# MODEL SETUP (Lazy initialization)
# =============================================================================

_model: OpenAIChatModel | None = None
_agent: Agent[AgentDeps, SupportResponse] | None = None


def _get_model() -> OpenAIChatModel:
    """Get or create OpenAI model (lazy initialization)."""
    global _model
    if _model is None:
        if settings.LLM_PROVIDER == "openai":
            api_key = settings.OPENAI_API_KEY.get_secret_value()
            base_url = "https://api.openai.com/v1"
            model_name = settings.LLM_MODEL_GPT
        else:
            api_key = settings.OPENROUTER_API_KEY.get_secret_value()
            base_url = settings.OPENROUTER_BASE_URL
            model_name = (
                settings.LLM_MODEL_GROK
                if settings.LLM_PROVIDER == "openrouter"
                else settings.AI_MODEL
            )

        if not api_key:
            # Fallback or error
            logger.warning("API Key missing for provider %s", settings.LLM_PROVIDER)
            # Try OpenRouter as fallback if OpenAI missing
            if settings.LLM_PROVIDER == "openai":
                api_key = settings.OPENROUTER_API_KEY.get_secret_value()
                base_url = settings.OPENROUTER_BASE_URL
                model_name = settings.AI_MODEL

        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        provider = OpenAIProvider(openai_client=client)
        _model = OpenAIChatModel(model_name, provider=provider)
    return _model


def _get_base_prompt() -> str:
    """Get system prompt (lazy load)."""
    return registry.get("system.main").content


async def _add_manager_snippets(ctx: RunContext[AgentDeps]) -> str:
    """Inject manager canned templates (editable via prompt file)."""
    try:
        content = registry.get("system.snippets").content
        logger.info(
            "📋 Manager snippets injected (%d chars, version=%s)",
            len(content),
            registry.get("system.snippets").metadata.get("version", "unknown"),
        )
        return "\n--- ШАБЛОНИ МЕНЕДЖЕРА ---\n" + content
    except (FileNotFoundError, ValueError) as e:
        logger.warning("Manager snippets not found: %s", e)
        return ""


async def _add_payment_requisites(ctx: RunContext[AgentDeps]) -> str:
    """Inject canonical payment requisites to avoid LLM hallucinations."""
    # НЕ показуй технічні заголовки клієнту - просто реквізити
    return format_requisites_multiline()


# =============================================================================
# DYNAMIC PROMPTS (registered via function)
# =============================================================================


async def _add_state_context(ctx: RunContext[AgentDeps]) -> str:
    """Add current state and customer context to prompt."""
    deps = ctx.deps

    lines = [
        "\n--- КОНТЕКСТ СЕСІЇ ---",
        f"Session ID: {deps.session_id}",
        f"Поточний стан: {deps.current_state}",
        f"Канал: {deps.channel}",
    ]

    if any([deps.customer_name, deps.customer_phone, deps.customer_city]):
        lines.append("\n--- ДАНІ КЛІЄНТА ---")
        lines.append(deps.get_customer_data_summary())

    if deps.selected_products:
        lines.append("\n--- ВИБРАНІ ТОВАРИ ---")
        for p in deps.selected_products[:3]:
            lines.append(f"- {p.get('name', 'Товар')}: {p.get('price', 0)} грн")

    return "\n".join(lines)


async def _add_memory_context(ctx: RunContext[AgentDeps]) -> str:
    """
    Add memory context (Titans-like) to prompt.

    This injects persistent profile and fluid facts from memory system.
    Populated by memory_context_node before agent execution.
    """
    deps = ctx.deps

    # Use pre-formatted memory context if available
    memory_prompt = deps.get_memory_context_prompt()

    if memory_prompt:
        logger.debug(
            "📚 Memory context injected (%d chars)",
            len(memory_prompt),
        )
        return f"\n{memory_prompt}"

    return ""


async def _add_image_context(ctx: RunContext[AgentDeps]) -> str:
    """Add image analysis instructions if image present."""
    if not ctx.deps.has_image:
        return ""

    return """
--- ФОТО ВІД КЛІЄНТА ---
ВАЖЛИВО: Користувач надіслав ФОТО!
1. Проаналізуй фото та визнач товар з EMBEDDED CATALOG
2. Якщо знайшов товар - ОДРАЗУ дай ціну та запропонуй розмір
3. Intent має бути PHOTO_IDENT
4. Не питай 'що вас цікавить' - відповідай конкретно!
"""


async def _add_state_instructions(ctx: RunContext[AgentDeps]) -> str:
    """
    Add state-specific behavioral instructions.

    QUALITY: Пріоритет промптів:
    1. state_specific_prompt з deps (injected by agent_node)
    2. Промпт з registry (state.STATE_X_Y)
    """
    deps = ctx.deps
    state = deps.current_state

    # QUALITY: Prefer injected state_specific_prompt (from state_prompts.py)
    if deps.state_specific_prompt:
        logger.info(
            "📋 Using injected state prompt for %s (%d chars)",
            state,
            len(deps.state_specific_prompt),
        )
        return f"\n--- ІНСТРУКЦІЯ ДЛЯ СТАНУ ({state}) ---\n{deps.state_specific_prompt}"

    # Fallback to registry
    try:
        prompt = registry.get(f"state.{state}")
        logger.info(
            "📋 Loaded state prompt from registry for %s (%d chars)", state, len(prompt.content)
        )
        return f"\n--- ІНСТРУКЦІЯ ДЛЯ СТАНУ ({state}) ---\n{prompt.content}"
    except (FileNotFoundError, ValueError) as e:
        logger.warning("No prompt found for state: %s (%s)", state, e)
        return ""


# =============================================================================
# TOOLS (registered via function)
# =============================================================================


async def _get_size_recommendation(
    ctx: RunContext[AgentDeps],
    height_cm: int,
) -> str:
    """
    Отримати рекомендацію розміру за зростом.

    Використовує формат: "Вам чудово підійде наш розмір {size}, він іде фактично до зросту {max_height} см👌"

    ЗАЛІЗОБЕТОННЕ ПРАВИЛО: На межах (120, 131, 143, 155) НЕ переходимо в більший розмір!
    
    Лінійка відповідності:
    - 110-120 см включно → 110-116
    - 121-131 см включно → 122-128
    - 132-143 см включно → 134-140
    - 144-155 см включно → 146-152
    - 156-168 см включно → 158-164
    """
    from src.agents.langgraph.nodes.utils import get_size_recommendation_text
    from src.agents.langgraph.nodes.helpers.size_parsing import height_to_size

    # Edge cases
    if height_cm < 80:
        return "Наш найменший розмір розрахований на зріст від 80 см. Якщо малюк трохи менший - можна взяти 80-92, він сяде вільніше і буде на виріст 🤍"

    if height_cm > 168:
        return "Наш найбільший розмір 158-164 на зріст до 168 см. Якщо потрібно більше - напишіть, я уточню у колег, чи є варіанти."

    # Використовуємо height_to_size з правильною логікою граничних значень
    size_label = height_to_size(height_cm)
    return get_size_recommendation_text(size_label)


async def _check_customer_data(ctx: RunContext[AgentDeps]) -> str:
    """Перевірити які дані клієнта вже зібрані."""
    deps = ctx.deps
    collected, missing = [], []

    if deps.customer_name:
        collected.append(f"ПІБ: {deps.customer_name}")
    else:
        missing.append("ПІБ")

    if deps.customer_phone:
        collected.append(f"Телефон: {deps.customer_phone}")
    else:
        missing.append("Телефон")

    if deps.customer_city:
        collected.append(f"Місто: {deps.customer_city}")
    else:
        missing.append("Місто")

    if deps.customer_nova_poshta:
        collected.append(f"Відділення НП: {deps.customer_nova_poshta}")
    else:
        missing.append("Відділення НП")

    result = []
    if collected:
        result.append(f"Зібрано: {', '.join(collected)}")
    if missing:
        result.append(f"Потрібно ще: {', '.join(missing)}")

    return "\n".join(result) if result else "Дані не зібрані"


async def _get_order_summary(ctx: RunContext[AgentDeps]) -> str:
    """Отримати підсумок замовлення."""
    products = ctx.deps.selected_products

    if not products:
        return "Товари ще не вибрані"

    lines = ["Замовлення:"]
    total = 0.0

    for p in products:
        name = p.get("name", "Товар")
        price = p.get("price", 0)
        size = p.get("size", "")

        line = f"- {name}"
        if size:
            line += f" (розмір {size})"
        line += f": {price} грн"

        lines.append(line)
        total += price

    lines.append(f"\nРазом: {total} грн")
    return "\n".join(lines)


async def _search_products(
    ctx: RunContext[AgentDeps],
    query: str,
    category: str | None = None,
) -> str:
    """
    Знайти товари в каталозі.

    Використовуй це коли клієнт питає про наявність або просить показати товари.
    """
    products = await ctx.deps.catalog.search_products(query, category)

    if not products:
        return get_human_response("not_found")

    lines = ["Знайдені товари:"]
    for p in products:
        name = p.get("name")
        price = p.get("price")
        sizes = ", ".join(p.get("sizes", []))
        colors = ", ".join(p.get("colors", []))
        lines.append(f"- {name} ({price} грн). Розміри: {sizes}. Кольори: {colors}")

    return "\n".join(lines)


# =============================================================================
# REGISTRATION FUNCTIONS
# =============================================================================


def _register_dynamic_prompts(agent: Agent[AgentDeps, SupportResponse]) -> None:
    """Register dynamic system prompts with the agent."""
    agent.system_prompt(_add_manager_snippets)
    agent.system_prompt(_add_payment_requisites)
    agent.system_prompt(_add_state_context)
    agent.system_prompt(_add_memory_context)  # Titans-like memory context
    agent.system_prompt(_add_image_context)
    agent.system_prompt(_add_state_instructions)


def _register_tools(agent: Agent[AgentDeps, SupportResponse]) -> None:
    """Register tools with the agent using decorator syntax."""
    agent.tool(name="get_size_recommendation")(_get_size_recommendation)
    agent.tool(name="check_customer_data")(_check_customer_data)
    agent.tool(name="get_order_summary")(_get_order_summary)
    agent.tool(name="search_products")(_search_products)


# =============================================================================
# AGENT FACTORY (Lazy initialization)
# =============================================================================


def get_support_agent() -> Agent[AgentDeps, SupportResponse]:
    """Get or create the support agent (lazy initialization)."""
    global _agent
    if _agent is None:
        _agent = Agent(  # type: ignore[call-overload]
            _get_model(),
            deps_type=AgentDeps,
            output_type=SupportResponse,  # Changed from result_type (PydanticAI 1.23+)
            system_prompt=_get_base_prompt(),
            retries=2,
        )
        _register_dynamic_prompts(_agent)
        _register_tools(_agent)

    return _agent


# =============================================================================
# RUNNER FUNCTION (for LangGraph nodes)
# =============================================================================


async def run_support(
    message: str,
    deps: AgentDeps,
    message_history: list[Any] | None = None,
) -> SupportResponse:
    """
    Run support agent and return structured response.

    This is what LangGraph nodes call.

    Args:
        message: User message
        deps: Injected dependencies
        message_history: Previous messages (Pydantic AI format)

    Returns:
        Validated SupportResponse
    """
    import asyncio

    agent = get_support_agent()

    try:
        result = await asyncio.wait_for(
            agent.run(
                message,
                deps=deps,
                message_history=message_history,
            ),
            timeout=45,  # Reduced to cap max response time
        )

        # result.output is the typed output (SupportResponse)
        # Note: output_type param (not result_type) but result.output (not result.response)
        return result.output

    except TimeoutError:
        logger.error("Support agent timeout for session %s", deps.session_id)
        return SupportResponse(
            event="escalation",
            messages=[MessageItem(content=_get_timeout_response())],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L1",
            ),
            escalation=EscalationInfo(reason="LLM_TIMEOUT"),
        )

    except Exception as e:
        logger.exception("Support agent error: %s", e)
        return SupportResponse(
            event="escalation",
            messages=[MessageItem(content=_get_error_response())],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason=f"AGENT_ERROR: {str(e)[:100]}"),
        )
