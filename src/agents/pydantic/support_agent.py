"""
Support/Sales Agent - Based on system_prompt_full.yaml
=======================================================
MIRT AI AGENT v7.0 - "Ольга"

IDENTITY (BLOCK 2):
- role: "AI-консультант магазину дитячого одягу MIRT"
- agent_name: "Ольга"
- personality: "Жива людина: можу перепитати, можу чесно сказати, якщо не впевнена."

IMMUTABLE_RULES:
- [P0] Мова відповіді ТІЛЬКИ українська
- [P0] ЗАБОРОНЕНО вигадувати товари, кольори, розміри, ціни - ТІЛЬКИ з CATALOG
- [P0] Максимум 900 символів у відповіді
- [P0] На межі розміру (120, 131, 143 см) = БІЛЬШИЙ розмір для запасу!

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
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.conf.config import settings
from src.core.prompt_loader import get_system_prompt_text

from .deps import AgentDeps
from .models import (
    EscalationInfo,
    MessageItem,
    ResponseMetadata,
    SupportResponse,
)


logger = logging.getLogger(__name__)


# =============================================================================
# MODEL SETUP (Lazy initialization)
# =============================================================================

_model: OpenAIModel | None = None
_agent: Agent[AgentDeps, SupportResponse] | None = None


def _get_model() -> OpenAIModel:
    """Get or create OpenAI model (lazy initialization)."""
    global _model
    if _model is None:
        api_key = settings.OPENROUTER_API_KEY.get_secret_value()
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is missing")

        client = AsyncOpenAI(
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=api_key,
        )
        provider = OpenAIProvider(openai_client=client)
        _model = OpenAIModel(settings.AI_MODEL, provider=provider)
    return _model


def _get_base_prompt() -> str:
    """Get system prompt (lazy load)."""
    return get_system_prompt_text("grok")


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
    """Add state-specific behavioral instructions."""
    state = ctx.deps.current_state

    instructions = {
        "STATE_0_INIT": "Привітай клієнта тепло. Запитай чим можеш допомогти.",
        "STATE_1_DISCOVERY": "Допоможи знайти потрібний товар. Запитай про зріст/вік дитини.",
        "STATE_2_VISION": "Аналізуй фото і пропонуй товар з каталогу.",
        "STATE_3_SIZE_COLOR": "Допоможи з розміром. Використай розмірну сітку.",
        "STATE_4_OFFER": "Зроби конкретну пропозицію з ціною. Запитай чи оформлюємо.",
        "STATE_5_PAYMENT_DELIVERY": "Збирай дані для доставки: ПІБ, телефон, місто, НП.",
        "STATE_6_UPSELL": "Запропонуй аксесуар. Не наполягай якщо відмовляються.",
        "STATE_7_END": "Подякуй за замовлення. Нагадай про термін доставки.",
        "STATE_8_COMPLAINT": "Вислухай скаргу. Передай менеджеру якщо потрібно.",
    }

    instruction = instructions.get(state, "")
    if instruction:
        return f"\n--- ІНСТРУКЦІЯ ДЛЯ СТАНУ ---\n{instruction}"
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

    SIZE_MAPPING (BLOCK 6):
    - 80-92 см -> 80-92
    - 93-99 см -> 98, 98-104
    - 100-105 см -> 104, 98-104, 110-116
    - 106-112 см -> 110, 110-116
    - 113-118 см -> 116, 110-116, 122-128
    - 119-125 см -> 122, 122-128
    - 126-133 см -> 128, 122-128, 134-140
    - 134-141 см -> 134, 134-140
    - 142-147 см -> 140, 146-152
    - 148-153 см -> 146, 146-152
    - 154-160 см -> 152, 158-164
    - 161-168 см -> 158, 164, 158-164

    [P0] На межі (120, 131, 143, 155 см) = БІЛЬШИЙ розмір!
    """
    # SIZE_MAPPING from system_prompt_full.yaml
    size_mapping = [
        (80, 92, ["80-92", "80", "86", "92"]),
        (93, 99, ["98", "98-104"]),
        (100, 105, ["104", "98-104", "110-116"]),
        (106, 112, ["110", "110-116"]),
        (113, 118, ["116", "110-116", "122-128"]),
        (119, 125, ["122", "122-128"]),
        (126, 133, ["128", "122-128", "134-140"]),
        (134, 141, ["134", "134-140"]),
        (142, 147, ["140", "146-152"]),
        (148, 153, ["146", "146-152"]),
        (154, 160, ["152", "158-164"]),
        (161, 168, ["158", "164", "158-164"]),
    ]

    # Edge cases
    if height_cm < 80:
        return "Наш найменший розмір розрахований на зріст від 80 см. Якщо малюк трохи менший - можна взяти 80-92, він сяде вільніше і буде на виріст 🤍"

    if height_cm > 168:
        return "Наш найбільший розмір 158-164 на зріст до 168 см. Якщо потрібно більше - напишіть, я уточню у колег, чи є варіанти."

    # Find matching range
    for min_h, max_h, sizes in size_mapping:
        if min_h <= height_cm <= max_h:
            preferred = sizes[0]
            return f"На зріст {height_cm} см найкраще підходить розмір {preferred} - він сідає зручно і не 'впритул' 🤍"

    # Border cases - always bigger size
    border_sizes = {120: "122-128", 131: "134-140", 143: "146-152", 155: "158-164"}
    if height_cm in border_sizes:
        return f"На зріст {height_cm} см (межа розмірів) рекомендую {border_sizes[height_cm]} - для запасу на виріст 🤍"

    return f"Для зросту {height_cm} см уточню у колег найкращий варіант."


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


# =============================================================================
# REGISTRATION FUNCTIONS
# =============================================================================


def _register_dynamic_prompts(agent: Agent[AgentDeps, SupportResponse]) -> None:
    """Register dynamic system prompts with the agent."""
    agent.system_prompt(_add_state_context)
    agent.system_prompt(_add_image_context)
    agent.system_prompt(_add_state_instructions)


def _register_tools(agent: Agent[AgentDeps, SupportResponse]) -> None:
    """Register tools with the agent using decorator syntax."""
    agent.tool(name="get_size_recommendation")(_get_size_recommendation)
    agent.tool(name="check_customer_data")(_check_customer_data)
    agent.tool(name="get_order_summary")(_get_order_summary)


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
            result_type=SupportResponse,
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
            timeout=30,
        )

        # result.output is already validated SupportResponse!
        return result.output

    except TimeoutError:
        logger.error("Support agent timeout for session %s", deps.session_id)
        return SupportResponse(
            event="escalation",
            messages=[MessageItem(content="Вибачте, система перевантажена. Спробуйте ще раз 🤍")],
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
            messages=[MessageItem(content="Вибачте, сталася помилка. Менеджер зв'яжеться з вами 🤍")],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason=f"AGENT_ERROR: {str(e)[:100]}"),
        )
