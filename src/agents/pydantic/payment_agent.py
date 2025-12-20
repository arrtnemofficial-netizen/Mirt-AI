"""
Payment Agent - Order and delivery specialist.
==============================================
Handles payment flow and customer data collection.
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.agents.langgraph.state_prompts import get_state_prompt
from src.conf.config import settings
from src.conf.payment_config import format_requisites_multiline
from src.core.human_responses import get_human_response

from .deps import AgentDeps
from .models import PaymentResponse


logger = logging.getLogger(__name__)


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
# PAYMENT AGENT
# =============================================================================


_PAYMENT_PROMPT_FALLBACK = """
Ти спеціаліст з оформлення замовлень MIRT_UA.
Збери дані для доставки: ПІБ, телефон, місто, відділення НП.
Використовуй реквізити з SSOT-блоку.
Відповідай УКРАЇНСЬКОЮ 🤍
"""


def _get_payment_prompt() -> str:
    """Get payment prompt from .md file with fallback."""
    try:
        from src.core.prompt_registry import registry

        return registry.get("system.payment").content
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Failed to load payment.md, using fallback: %s", e)
        return _PAYMENT_PROMPT_FALLBACK


_payment_agent: Agent[AgentDeps, PaymentResponse] | None = None


async def _add_order_context(ctx: RunContext[AgentDeps]) -> str:
    """Add order and customer context."""
    deps = ctx.deps
    lines = []

    # Products in order
    if deps.selected_products:
        lines.append("\n--- ЗАМОВЛЕННЯ ---")
        total = 0.0
        for p in deps.selected_products:
            name = p.get("name", "Товар")
            price = p.get("price", 0)
            lines.append(f"- {name}: {price} грн")
            total += price
        lines.append(f"Разом: {total} грн")

    # Already collected data
    lines.append("\n--- ЗІБРАНІ ДАНІ ---")
    if deps.customer_name:
        lines.append(f"ПІБ: {deps.customer_name} ✓")
    if deps.customer_phone:
        lines.append(f"Телефон: {deps.customer_phone} ✓")
    if deps.customer_city:
        lines.append(f"Місто: {deps.customer_city} ✓")
    if deps.customer_nova_poshta:
        lines.append(f"Відділення НП: {deps.customer_nova_poshta} ✓")

    # What's missing
    missing = []
    if not deps.customer_name:
        missing.append("ПІБ")
    if not deps.customer_phone:
        missing.append("Телефон")
    if not deps.customer_city:
        missing.append("Місто")
    if not deps.customer_nova_poshta:
        missing.append("Відділення НП")

    if missing:
        lines.append(f"\nПотрібно зібрати: {', '.join(missing)}")
    else:
        lines.append("\n✅ ВСІ ДАНІ ЗІБРАНІ - можна надавати реквізити!")

    return "\n".join(lines)


async def _add_payment_requisites(ctx: RunContext[AgentDeps]) -> str:
    """Inject canonical payment requisites to avoid hallucinations."""
    return "\n--- РЕКВІЗИТИ ДЛЯ ОПЛАТИ (SSOT) ---\n" + format_requisites_multiline()


async def _add_payment_subphase_prompt(ctx: RunContext[AgentDeps]) -> str:
    """Inject payment sub-phase instructions from markdown prompts (SSOT)."""
    sub_phase = getattr(ctx.deps, "payment_sub_phase", None) or "REQUEST_DATA"
    try:
        prompt = get_state_prompt("STATE_5_PAYMENT_DELIVERY", sub_phase=sub_phase)
        return "\n--- PAYMENT SUB-PHASE PROMPT (SSOT) ---\n" + prompt
    except Exception:
        return ""


async def _extract_customer_data(
    ctx: RunContext[AgentDeps],
    name: str | None = None,
    phone: str | None = None,
    city: str | None = None,
    nova_poshta: str | None = None,
) -> str:
    """Зберегти дані клієнта витягнуті з повідомлення."""
    saved = []
    if name:
        ctx.deps.customer_name = name
        saved.append(f"ПІБ: {name}")
    if phone:
        ctx.deps.customer_phone = phone
        saved.append(f"Телефон: {phone}")
    if city:
        ctx.deps.customer_city = city
        saved.append(f"Місто: {city}")
    if nova_poshta:
        ctx.deps.customer_nova_poshta = nova_poshta
        saved.append(f"Відділення НП: {nova_poshta}")
    if saved:
        return f"Збережено: {', '.join(saved)}"
    return "Нові дані не надано"


async def _check_order_ready(ctx: RunContext[AgentDeps]) -> str:
    """Перевірити чи замовлення готове до оформлення."""
    deps = ctx.deps
    if not deps.selected_products:
        return "❌ Товари не вибрані"
    missing = []
    if not deps.customer_name:
        missing.append("ПІБ")
    if not deps.customer_phone:
        missing.append("Телефон")
    if not deps.customer_city:
        missing.append("Місто")
    if not deps.customer_nova_poshta:
        missing.append("Відділення НП")
    if missing:
        return f"❌ Потрібно ще: {', '.join(missing)}"
    return "✅ Замовлення готове! Можна надавати реквізити для оплати."


def get_payment_agent() -> Agent[AgentDeps, PaymentResponse]:
    """Get or create payment agent (lazy initialization)."""
    global _payment_agent
    if _payment_agent is None:
        _payment_agent = Agent(  # type: ignore[call-overload]
            _build_model(),
            deps_type=AgentDeps,
            output_type=PaymentResponse,  # Changed from result_type (PydanticAI 1.23+)
            system_prompt=_get_payment_prompt(),
            retries=2,
        )
        _payment_agent.system_prompt(_add_order_context)
        _payment_agent.system_prompt(_add_payment_requisites)
        _payment_agent.system_prompt(_add_payment_subphase_prompt)
        # Register tools - use decorator syntax
        _payment_agent.tool(name="extract_customer_data")(_extract_customer_data)
        _payment_agent.tool(name="check_order_ready")(_check_order_ready)
    return _payment_agent


# Backward compatibility - removed unused property


# =============================================================================
# RUNNER
# =============================================================================


async def run_payment(
    message: str,
    deps: AgentDeps,
    message_history: list[Any] | None = None,
) -> PaymentResponse:
    """
    Run payment agent for order processing.

    Args:
        message: User message
        deps: Dependencies with customer data
        message_history: Previous messages

    Returns:
        Validated PaymentResponse
    """
    import asyncio

    agent = get_payment_agent()

    try:
        result = await asyncio.wait_for(
            agent.run(message, deps=deps, message_history=message_history),
            timeout=30,
        )
        return result.output  # output_type param, result.output attr

    except Exception as e:
        logger.exception("Payment agent error: %s", e)
        return PaymentResponse(
            reply_to_user=get_human_response("payment_error"),
            missing_fields=["name", "phone", "city", "nova_poshta"],
            order_ready=False,
        )
