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
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.conf.config import settings
from src.core.human_responses import get_human_response
from src.core.prompt_registry import registry
from src.services.domain.payment.payment_config import get_payment_section
from src.services.domain.payment.payment_validation import (
    get_payment_sub_phase,
    is_order_ready,
    validate_phone_number,
)

from .deps import AgentDeps
from .models import PaymentResponse


logger = logging.getLogger(__name__)


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

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    provider = OpenAIProvider(openai_client=client)
    return OpenAIModel(model_name, provider=provider)


_PAYMENT_PROMPT_FALLBACK = (
    "You handle order and delivery. Collect full name, phone, city, and branch. "
    "Confirm the order and provide payment requisites."
)


def _get_payment_prompt() -> str:
    """Get payment prompt from registry with ASCII fallback."""
    try:
        base_identity = registry.get("system.base_identity").content
        domain_prompt = registry.get("payment.main").content
        return f"{base_identity}\n\n{domain_prompt}"
    except Exception as e:
        logger.warning("Failed to load payment main prompt: %s", e)
        return _PAYMENT_PROMPT_FALLBACK


def _label(labels: dict[str, Any], key: str, default: str) -> str:
    value = labels.get(key)
    return value if isinstance(value, str) and value else default


def _get_order_labels() -> dict[str, Any]:
    return get_payment_section("order_context")


def _build_order_context(deps: AgentDeps) -> str:
    labels = _get_order_labels()
    currency = _label(labels, "currency", "UAH")
    ok_mark = _label(labels, "ok_mark", "OK")

    lines: list[str] = []

    if deps.selected_products:
        header = _label(labels, "order_header", "ORDER")
        lines.append(f"\n--- {header} ---")
        total = 0.0
        for product in deps.selected_products:
            name = product.get("name") or _label(labels, "default_product", "Product")
            price = product.get("price", 0)
            lines.append(f"- {name}: {price} {currency}")
            total += float(price or 0)
        total_label = _label(labels, "total_label", "Total")
        lines.append(f"{total_label}: {total} {currency}")

    collected_header = _label(labels, "collected_header", "COLLECTED DATA")
    lines.append(f"\n--- {collected_header} ---")
    if deps.customer_name:
        lines.append(f"{_label(labels, 'label_name', 'Full name')}: {deps.customer_name} {ok_mark}")
    if deps.customer_phone:
        lines.append(f"{_label(labels, 'label_phone', 'Phone')}: {deps.customer_phone} {ok_mark}")
    if deps.customer_city:
        lines.append(f"{_label(labels, 'label_city', 'City')}: {deps.customer_city} {ok_mark}")
    if deps.customer_nova_poshta:
        lines.append(
            f"{_label(labels, 'label_branch', 'Branch')}: {deps.customer_nova_poshta} {ok_mark}"
        )

    image_header = _label(labels, "image_context_header", "IMAGE CONTEXT")
    lines.append(f"\n--- {image_header} ---")
    lines.append(f"{_label(labels, 'image_has_image_label', 'has_image')}: {bool(deps.has_image)}")
    if deps.image_url:
        lines.append(f"{_label(labels, 'image_url_label', 'image_url')}: {deps.image_url}")

    missing = []
    if not deps.customer_name:
        missing.append(_label(labels, "label_name", "Full name"))
    if not deps.customer_phone:
        missing.append(_label(labels, "label_phone", "Phone"))
    if not deps.customer_city:
        missing.append(_label(labels, "label_city", "City"))
    if not deps.customer_nova_poshta:
        missing.append(_label(labels, "label_branch", "Branch"))

    if missing:
        prefix = _label(labels, "missing_prefix", "Missing")
        lines.append(f"\n{prefix}: {', '.join(missing)}")
    else:
        ready_note = _label(labels, "ready_note", "All required data collected.")
        lines.append(f"\n{ready_note}")

    return "\n".join(lines)


async def _add_order_context(ctx: RunContext[AgentDeps]) -> str:
    """Add order and customer context."""
    return _build_order_context(ctx.deps)


async def _add_payment_requisites(ctx: RunContext[AgentDeps]) -> str:
    """Inject canonical payment requisites to avoid hallucinations."""
    section = get_payment_section("payment_requisites")
    header = section.get("header", "PAYMENT REQUISITES")
    body = section.get("body", "")
    if not isinstance(header, str) or not isinstance(body, str) or not body.strip():
        return ""
    return f"\n--- {header} ---\n{body}".rstrip()


async def _add_payment_subphase_prompt(ctx: RunContext[AgentDeps]) -> str:
    """Expose payment sub-phase for reasoning."""
    labels = get_payment_section("payment_subphase")
    header = labels.get("header", "PAYMENT SUBPHASE")
    metadata = {
        "customer_name": ctx.deps.customer_name,
        "customer_phone": ctx.deps.customer_phone,
        "customer_city": ctx.deps.customer_city,
        "customer_nova_poshta": ctx.deps.customer_nova_poshta,
    }
    sub_phase = get_payment_sub_phase(metadata)
    return f"\n--- {header} ---\n{sub_phase}"


_payment_agent: Agent[AgentDeps, PaymentResponse] | None = None


async def _extract_customer_data(
    ctx: RunContext[AgentDeps],
    name: str | None = None,
    phone: str | None = None,
    city: str | None = None,
    nova_poshta: str | None = None,
) -> str:
    """Persist extracted customer data."""
    labels = _get_order_labels()
    saved_prefix = _label(labels, "saved_prefix", "Saved")
    no_new_data = _label(labels, "no_new_data", "No new data")
    invalid_phone_note = _label(labels, "invalid_phone_note", "invalid phone format")

    saved = []
    if name:
        ctx.deps.customer_name = name
        saved.append(f"{_label(labels, 'label_name', 'Full name')}: {name}")
    if phone:
        valid_phone = validate_phone_number(phone)
        if valid_phone:
            ctx.deps.customer_phone = valid_phone
            saved.append(f"{_label(labels, 'label_phone', 'Phone')}: {valid_phone}")
        else:
            ctx.deps.customer_phone = phone
            saved.append(f"{_label(labels, 'label_phone', 'Phone')}: {phone} ({invalid_phone_note})")
    if city:
        ctx.deps.customer_city = city
        saved.append(f"{_label(labels, 'label_city', 'City')}: {city}")
    if nova_poshta:
        ctx.deps.customer_nova_poshta = nova_poshta
        saved.append(f"{_label(labels, 'label_branch', 'Branch')}: {nova_poshta}")

    if saved:
        return f"{saved_prefix}: {', '.join(saved)}"
    return no_new_data


async def _check_order_ready(ctx: RunContext[AgentDeps]) -> str:
    """Check if order is ready for checkout."""
    labels = _get_order_labels()

    deps = ctx.deps
    if not deps.selected_products:
        return _label(labels, "order_not_ready_products", "No products selected")

    metadata = {
        "customer_name": deps.customer_name,
        "customer_phone": deps.customer_phone,
        "customer_city": deps.customer_city,
        "customer_nova_poshta": deps.customer_nova_poshta,
    }

    ready, missing = is_order_ready(metadata)
    if not ready:
        prefix = _label(labels, "order_not_ready_missing", "Missing")
        return f"{prefix}: {', '.join(missing)}"

    return _label(labels, "order_ready", "Order is ready for payment.")


def get_payment_agent() -> Agent[AgentDeps, PaymentResponse]:
    """Get or create payment agent (lazy initialization)."""
    global _payment_agent
    if _payment_agent is None:
        _payment_agent = Agent(  # type: ignore[call-overload]
            _build_model(),
            deps_type=AgentDeps,
            output_type=PaymentResponse,
            system_prompt=_get_payment_prompt(),
            retries=2,
        )
        _payment_agent.system_prompt(_add_order_context)
        _payment_agent.system_prompt(_add_payment_requisites)
        _payment_agent.system_prompt(_add_payment_subphase_prompt)
        _payment_agent.tool(name="extract_customer_data")(_extract_customer_data)
        _payment_agent.tool(name="check_order_ready")(_check_order_ready)
    return _payment_agent


# =============================================================================
# RUNNER
# =============================================================================


async def run_payment(
    message: str,
    deps: AgentDeps,
    message_history: list[Any] | None = None,
) -> PaymentResponse:
    """Run payment agent for order processing."""
    import asyncio

    agent = get_payment_agent()

    try:
        result = await asyncio.wait_for(
            agent.run(message, deps=deps, message_history=message_history),
            timeout=30,
        )
        return result.output

    except Exception as e:
        logger.exception("Payment agent error: %s", e)
        return PaymentResponse(
            reply_to_user=get_human_response("payment_error"),
            missing_fields=["name", "phone", "city", "nova_poshta"],
            order_ready=False,
        )
