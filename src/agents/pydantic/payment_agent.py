"""
Payment Agent - Order and delivery specialist.
==============================================
Handles payment flow and customer data collection.
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext, RunUsage
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
    # SENIOR-LEVEL: Use AI_MODEL as single source of truth
    model_name = settings.AI_MODEL

    if settings.LLM_PROVIDER == "openai":
        api_key = settings.OPENAI_API_KEY.get_secret_value()
        base_url = "https://api.openai.com/v1"
    else:
        api_key = settings.OPENROUTER_API_KEY.get_secret_value()
        base_url = settings.OPENROUTER_BASE_URL

    if not api_key:
        logger.warning("API Key missing for provider %s", settings.LLM_PROVIDER)
        if settings.LLM_PROVIDER == "openai":
            api_key = settings.OPENROUTER_API_KEY.get_secret_value()
            base_url = settings.OPENROUTER_BASE_URL

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
    # НЕ показуй технічні заголовки клієнту - просто реквізити
    return format_requisites_multiline()


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
    import time

    from src.services.llm_usage_logger import log_llm_usage_best_effort

    agent = get_payment_agent()

    # Track latency and result for logging
    start_time = time.perf_counter()
    result = None
    response: PaymentResponse | None = None
    success = True
    error_message: str | None = None
    tokens_input = 0
    tokens_output = 0
    # SENIOR-LEVEL: Get model name from actual model, not hardcoded fallback
    model_name: str | None = None
    # Use AI_MODEL as single source of truth
    payment_model_name = settings.AI_MODEL

    try:
        result = await asyncio.wait_for(
            agent.run(message, deps=deps, message_history=message_history),
            timeout=30,
        )
        response = result.output  # output_type param, result.output attr

        # Try to extract usage from result (if available)
        if hasattr(result, "usage") and result.usage is not None:
            usage = result.usage
            # Check if usage is actually a RunUsage instance (not a function) and has actual values
            # First check it's not callable (function), then check it's RunUsage, then check has_values
            if not callable(usage) and isinstance(usage, RunUsage) and hasattr(usage, "has_values") and usage.has_values():
                if hasattr(usage, "input_tokens"):
                    tokens_input = usage.input_tokens or 0
                if hasattr(usage, "output_tokens"):
                    tokens_output = usage.output_tokens or 0
                # Fallback: if individual tokens are 0 but total_tokens exists, estimate
                if tokens_input == 0 and tokens_output == 0 and hasattr(usage, "total_tokens"):
                    total = usage.total_tokens or 0
                    if total > 0:
                        # Rough estimate: 70% input, 30% output (typical for chat)
                        tokens_input = int(total * 0.7)
                        tokens_output = int(total * 0.3)
                        logger.debug(
                            "[TOKEN_EXTRACTION] Estimated tokens from total: in=%d out=%d (total=%d)",
                            tokens_input, tokens_output, total
                        )
            else:
                logger.debug("[TOKEN_EXTRACTION] Usage object exists but has no values")
        elif hasattr(result, "model_used"):
            model_name = str(result.model_used)

        # Extract model from agent if not in result
        if not model_name and hasattr(agent, "model"):
            if hasattr(agent.model, "model_id"):
                model_name = agent.model.model_id
            elif hasattr(agent.model, "name"):
                model_name = agent.model.name

        # SENIOR-LEVEL: Fallback to actual payment model from settings, not hardcoded
        if not model_name:
            model_name = payment_model_name

        return response

    except Exception as e:
        success = False
        error_message = f"PAYMENT_ERROR: {str(e)[:100]}"
        logger.exception("Payment agent error: %s", e)
        response = PaymentResponse(
            reply_to_user=get_human_response("payment_error"),
            missing_fields=["name", "phone", "city", "nova_poshta"],
            order_ready=False,
        )
        return response

    finally:
        # Log usage (best-effort, non-blocking)
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # Prepare minimal metadata for payment
        metadata: dict[str, Any] = {}
        if response:
            metadata["order_ready"] = response.order_ready
            if hasattr(deps, "dialog_phase"):
                metadata["dialog_phase"] = deps.dialog_phase

        # Extract model if not already set
        if not model_name:
            if hasattr(agent, "model"):
                if hasattr(agent.model, "model_id"):
                    model_name = agent.model.model_id
                elif hasattr(agent.model, "name"):
                    model_name = agent.model.name
            if not model_name:
                model_name = payment_model_name

        # SENIOR-LEVEL: Use actual payment model, not hardcoded fallback
        # Log asynchronously (fire-and-forget)
        asyncio.create_task(
            log_llm_usage_best_effort(
                session_id=deps.session_id,
                model=model_name or payment_model_name,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                latency_ms=latency_ms,
                success=success,
                error_message=error_message,
                metadata=metadata if metadata else None,
                user_id=str(deps.user_id) if hasattr(deps, "user_id") and deps.user_id else None,
            )
        )
