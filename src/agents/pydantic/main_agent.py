"""
Support/Sales Agent - PydanticAI main agent.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.conf.config import settings
from src.core.circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
from src.core.prompt_registry import registry
from src.agents.pydantic.main_agent_config import (
    get_main_agent_section,
    get_main_agent_value,
)
from src.services.domain.payment.payment_config import get_payment_section

from .deps import AgentDeps
from .models import (
    EscalationInfo,
    MessageItem,
    OfferResponse,
    ResponseMetadata,
    SupportResponse,
)


logger = logging.getLogger(__name__)


def _get_main_section(name: str) -> dict[str, object]:
    data = get_main_agent_section(name)
    return data if isinstance(data, dict) else {}


def _get_main_value(section: str, key: str, default: str) -> str:
    return get_main_agent_value(section, key, default)


def _format_payment_requisites() -> str:
    requisites = get_payment_section("payment_requisites")
    if not requisites:
        return ""
    header = str(requisites.get("header") or "PAYMENT REQUISITES")
    body = str(requisites.get("body") or "").strip()
    if not body:
        return ""
    return f"\n--- {header} ---\n{body}"


def _get_error_text(key: str, default: str) -> str:
    errors = _get_main_section("errors")
    value = errors.get(key) if isinstance(errors, dict) else None
    return str(value) if isinstance(value, str) and value else default


def _get_error_response() -> str:
    return _get_error_text("generic", "An error occurred.")


# =============================================================================
# MODEL SETUP (Lazy initialization)
# =============================================================================

_model: OpenAIModel | None = None
_agent: Agent[AgentDeps, SupportResponse] | None = None
_offer_agent: Agent[AgentDeps, OfferResponse] | None = None


def _get_model() -> OpenAIModel:
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
            model_name = settings.LLM_MODEL_GROK if settings.LLM_PROVIDER == "openrouter" else settings.AI_MODEL

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
        _model = OpenAIModel(model_name, provider=provider)
    return _model


def _get_base_prompt() -> str:
    """Get system prompt (lazy load)."""
    base_identity = registry.get("system.base_identity").content
    domain_prompt = registry.get("main.main").content
    return f"{base_identity}\n\n{domain_prompt}"


async def _add_manager_snippets(ctx: RunContext[AgentDeps]) -> str:
    """Inject manager canned templates (editable via prompt file)."""
    try:
        content = registry.get("system.snippets").content
        logger.info(
            "Manager snippets injected (%d chars, version=%s)",
            len(content),
            registry.get("system.snippets").metadata.get("version", "unknown"),
        )
        header = _get_main_value("headers", "manager_snippets", "MANAGER SNIPPETS")
        return f"\n--- {header} ---\n{content}"
    except (FileNotFoundError, ValueError) as e:
        logger.warning("Manager snippets not found: %s", e)
        return ""


async def _add_payment_requisites(ctx: RunContext[AgentDeps]) -> str:
    """Inject canonical payment requisites to avoid LLM hallucinations."""
    return _format_payment_requisites()


# =============================================================================
# DYNAMIC PROMPTS (registered via function)
# =============================================================================


async def _add_state_context(ctx: RunContext[AgentDeps]) -> str:
    """Add current state and customer context to prompt."""
    deps = ctx.deps

    headers = _get_main_section("headers")
    labels = _get_main_section("labels")

    lines = [
        f"\n--- {headers.get('session_context', 'SESSION CONTEXT')} ---",
        f"Session ID: {deps.session_id}",
        f"{labels.get('current_state', 'Current state')}: {deps.current_state}",
        f"{labels.get('channel', 'Channel')}: {deps.channel}",
    ]

    if any([deps.customer_name, deps.customer_phone, deps.customer_city]):
        lines.append(f"\n--- {headers.get('customer_data', 'CUSTOMER DATA')} ---")
        lines.append(deps.get_customer_data_summary())

    if deps.selected_products:
        lines.append(f"\n--- {headers.get('selected_products', 'SELECTED PRODUCTS')} ---")
        for p in deps.selected_products[:3]:
            lines.append(
                f"- {p.get('name', labels.get('default_product', 'Product'))}: "
                f"{p.get('price', 0)} {labels.get('currency', 'UAH')}"
            )

    return "\n".join(lines)


async def _add_memory_context(ctx: RunContext[AgentDeps]) -> str:
    """Add memory context when available."""
    prompt = getattr(ctx.deps, "memory_context_prompt", None)
    if not prompt:
        return ""
    header = _get_main_value("headers", "memory_context", "MEMORY CONTEXT")
    return f"\n--- {header} ---\n{prompt}"


async def _add_image_context(ctx: RunContext[AgentDeps]) -> str:
    """Add image analysis instructions if image present."""
    if not ctx.deps.has_image:
        return ""
    photo_context = _get_main_section("photo_context")
    block = photo_context.get("block", "")
    return str(block).strip()


async def _add_state_instructions(ctx: RunContext[AgentDeps]) -> str:
    """Add state-specific behavioral instructions."""
    state = ctx.deps.current_state
    instructions = _get_main_section("state_instructions")
    instruction = instructions.get(state, "") if isinstance(instructions, dict) else ""
    if instruction:
        header = _get_main_value("headers", "state_instruction", "STATE INSTRUCTION")
        return f"\n--- {header} ---\n{instruction}"
    return ""


# =============================================================================
# TOOLS (registered via function)
# =============================================================================

@lru_cache(maxsize=1)
def _load_size_mapping() -> tuple[list[dict[str, object]], dict[int, str]]:
    """Load size mapping from SSOT YAML with a safe fallback."""
    path = (
        Path(__file__).parent.parent.parent.parent
        / "data"
        / "prompts"
        / "system"
        / "size_guide.yaml"
    )

    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        size_mapping = data.get("size_mapping", [])
        border_sizes = data.get("border_sizes", {})
        if isinstance(size_mapping, list) and isinstance(border_sizes, dict):
            return size_mapping, border_sizes
    except Exception as e:
        logger.warning("Failed to load size_guide.yaml: %s", e)

    fallback_mapping = [
        {"min": 80, "max": 92, "sizes": ["80-92", "80", "86", "92"]},
        {"min": 93, "max": 99, "sizes": ["98", "98-104"]},
        {"min": 100, "max": 105, "sizes": ["104", "98-104", "110-116"]},
        {"min": 106, "max": 112, "sizes": ["110", "110-116"]},
        {"min": 113, "max": 118, "sizes": ["116", "110-116", "122-128"]},
        {"min": 119, "max": 125, "sizes": ["122", "122-128"]},
        {"min": 126, "max": 133, "sizes": ["128", "122-128", "134-140"]},
        {"min": 134, "max": 141, "sizes": ["134", "134-140"]},
        {"min": 142, "max": 147, "sizes": ["140", "146-152"]},
        {"min": 148, "max": 153, "sizes": ["146", "146-152"]},
        {"min": 154, "max": 160, "sizes": ["152", "158-164"]},
        {"min": 161, "max": 168, "sizes": ["158", "164", "158-164"]},
    ]
    fallback_border = {120: "122-128", 131: "134-140", 143: "146-152", 155: "158-164"}
    return fallback_mapping, fallback_border




async def _get_size_recommendation(
    ctx: RunContext[AgentDeps],
    height_cm: int,
) -> str:
    """
    Provide size recommendation based on height.
    """
    size_mapping, border_sizes = _load_size_mapping()
    size_templates = _get_main_section("size_recommendation")

    below_min = str(size_templates.get("below_min") or "Height below minimum.")
    above_max = str(size_templates.get("above_max") or "Height above maximum.")
    exact_tmpl = str(size_templates.get("exact") or "Height {height_cm} fits size {preferred}.")
    borderline_tmpl = str(
        size_templates.get("borderline") or "Height {height_cm} is borderline, choose {size}."
    )
    needs_detail_tmpl = str(
        size_templates.get("needs_detail") or "Height {height_cm} needs clarification."
    )

    if height_cm < 80:
        return below_min

    if height_cm > 168:
        return above_max

    for item in size_mapping:
        min_h = int(item.get("min", 0))
        max_h = int(item.get("max", 0))
        sizes = item.get("sizes", [])
        if min_h <= height_cm <= max_h and isinstance(sizes, list) and sizes:
            preferred = sizes[0]
            return exact_tmpl.format(height_cm=height_cm, preferred=preferred)

    if height_cm in border_sizes:
        return borderline_tmpl.format(height_cm=height_cm, size=border_sizes[height_cm])

    return needs_detail_tmpl.format(height_cm=height_cm)


async def _check_customer_data(ctx: RunContext[AgentDeps]) -> str:
    """Check which customer fields are already collected."""
    deps = ctx.deps
    collected, missing = [], []
    order_context = get_payment_section("order_context")
    label_name = str(order_context.get("label_name") or "Name")
    label_phone = str(order_context.get("label_phone") or "Phone")
    label_city = str(order_context.get("label_city") or "City")
    label_branch = str(order_context.get("label_branch") or "Branch")
    collected_header = str(order_context.get("collected_header") or "Collected")
    missing_prefix = str(order_context.get("missing_prefix") or "Missing")
    no_data = str(order_context.get("no_data") or "No data collected")

    if deps.customer_name:
        collected.append(f"{label_name}: {deps.customer_name}")
    else:
        missing.append(label_name)

    if deps.customer_phone:
        collected.append(f"{label_phone}: {deps.customer_phone}")
    else:
        missing.append(label_phone)

    if deps.customer_city:
        collected.append(f"{label_city}: {deps.customer_city}")
    else:
        missing.append(label_city)

    if deps.customer_nova_poshta:
        collected.append(f"{label_branch}: {deps.customer_nova_poshta}")
    else:
        missing.append(label_branch)

    result = []
    if collected:
        result.append(f"{collected_header}: {', '.join(collected)}")
    if missing:
        result.append(f"{missing_prefix}: {', '.join(missing)}")

    return "\n".join(result) if result else no_data


async def _get_order_summary(ctx: RunContext[AgentDeps]) -> str:
    """Get order summary."""
    products = ctx.deps.selected_products
    summary = _get_main_section("order_summary")
    labels = _get_main_section("labels")
    none_selected = str(summary.get("none_selected") or "No products selected")
    header = str(summary.get("header") or "Order")
    size_label = str(summary.get("size_label") or "size")
    total_label = str(summary.get("total_label") or "Total")
    currency = str(labels.get("currency") or "UAH")

    if not products:
        return none_selected

    lines = [f"{header}:"]
    total = 0.0

    for p in products:
        name = p.get("name", labels.get("default_product", "Product"))
        price = p.get("price", 0)
        size = p.get("size", "")

        line = f"- {name}"
        if size:
            line += f" ({size_label} {size})"
        line += f": {price} {currency}"

        lines.append(line)
        total += price

    lines.append(f"\n{total_label}: {total} {currency}")
    return "\n".join(lines)


async def _search_products(
    ctx: RunContext[AgentDeps],
    query: str,
    category: str | None = None,
) -> str:
    """
    Search products in the catalog.
    """
    products = await ctx.deps.catalog.search_products(query, category)

    search_cfg = _get_main_section("search")
    header = str(search_cfg.get("header") or "Found products")
    none_found = str(search_cfg.get("none_found") or "No products found.")
    line_template = str(
        search_cfg.get("line_template")
        or "- {name} ({price} UAH). Sizes: {sizes}. Colors: {colors}"
    )

    if not products:
        return none_found

    lines = [f"{header}:"]
    for p in products:
        name = p.get("name")
        price = p.get("price")
        sizes = ", ".join(p.get("sizes", []))
        colors = ", ".join(p.get("colors", []))
        lines.append(
            line_template.format(
                name=name,
                price=price,
                sizes=sizes,
                colors=colors,
            )
        )

    return "\n".join(lines)


# =============================================================================
# REGISTRATION FUNCTIONS
# =============================================================================


def _register_dynamic_prompts(agent: Agent[AgentDeps, Any]) -> None:
    """Register dynamic system prompts with the agent."""
    agent.system_prompt(_add_state_context)
    agent.system_prompt(_add_memory_context)
    agent.system_prompt(_add_image_context)
    agent.system_prompt(_add_state_instructions)


def _register_tools(agent: Agent[AgentDeps, Any]) -> None:
    """Register tools with the agent using decorator syntax."""
    agent.tool(name="get_size_recommendation")(_get_size_recommendation)
    agent.tool(name="check_customer_data")(_check_customer_data)
    agent.tool(name="get_order_summary")(_get_order_summary)
    agent.tool(name="search_products")(_search_products)


# =============================================================================
# AGENT FACTORY (Lazy initialization)
# =============================================================================


def get_main_agent() -> Agent[AgentDeps, SupportResponse]:
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


def get_offer_agent() -> Agent[AgentDeps, OfferResponse]:
    """Get or create the offer agent (lazy initialization)."""
    global _offer_agent
    if _offer_agent is None:
        _offer_agent = Agent(  # type: ignore[call-overload]
            _get_model(),
            deps_type=AgentDeps,
            output_type=OfferResponse,
            system_prompt=_get_base_prompt(),
            retries=2,
        )
        _register_dynamic_prompts(_offer_agent)
        _register_tools(_offer_agent)

    return _offer_agent


# =============================================================================
# CIRCUIT BREAKER (for LLM protection)
# =============================================================================

_llm_circuit_breaker = get_circuit_breaker(
    "pydantic_ai_main_agent",
    failure_threshold=3,
    recovery_timeout=60.0,
)


# =============================================================================
# RUNNER FUNCTION (for LangGraph nodes)
# =============================================================================


async def run_main(
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

    # Check circuit breaker before attempting LLM call
    if not _llm_circuit_breaker.can_execute():
        logger.warning(
            "Circuit breaker OPEN for main agent (session %s). Escalating.",
            deps.session_id,
        )
        return SupportResponse(
            event="escalation",
            messages=[
                MessageItem(
                    content=_get_error_text(
                        "overload",
                        "System temporarily unavailable. A manager will follow up.",
                    )
                )
            ],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason="CIRCUIT_BREAKER_OPEN"),
        )

    agent = get_main_agent()

    try:
        result = await asyncio.wait_for(
            agent.run(
                message,
                deps=deps,
                message_history=message_history,
            ),
            timeout=120,  # Increased for slow API tiers
        )

        # Record success in circuit breaker
        _llm_circuit_breaker.record_success()

        # Record tracing attributes
        if span:
            span.set_attribute("event", result.output.event)
            span.set_attribute("messages_count", len(result.output.messages))
            if result.output.products:
                span.set_attribute("products_count", len(result.output.products))

        # result.output is the typed output (SupportResponse)
        # Note: output_type param (not result_type) but result.output (not result.response)
        return result.output

    except TimeoutError:
        logger.error("Support agent timeout for session %s", deps.session_id)
        if span:
            span.set_attribute("error", True)
            span.set_attribute("error_type", "TimeoutError")
        timeout_error = TimeoutError("Support agent timeout")
        _llm_circuit_breaker.record_failure(timeout_error)
        return SupportResponse(
            event="escalation",
            messages=[
                MessageItem(
                    content=_get_error_text(
                        "overload",
                        "System overloaded. Please try again.",
                    )
                )
            ],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L1",
            ),
            escalation=EscalationInfo(reason="LLM_TIMEOUT"),
        )

    except CircuitBreakerOpenError:
        # Re-raise circuit breaker errors (shouldn't happen here, but handle gracefully)
        logger.error("Circuit breaker error for session %s", deps.session_id)
        return SupportResponse(
            event="escalation",
            messages=[
                MessageItem(
                    content=_get_error_text(
                        "overload",
                        "System temporarily unavailable. A manager will follow up.",
                    )
                )
            ],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason="CIRCUIT_BREAKER_OPEN"),
        )

    except Exception as e:
        logger.exception("Support agent error: %s", e)
        if span:
            span.set_attribute("error", True)
            span.set_attribute("error_type", type(e).__name__)
            span.set_attribute("error_message", str(e)[:200])
        _llm_circuit_breaker.record_failure(e)
        return SupportResponse(
            event="escalation",
            messages=[
                MessageItem(
                    content=_get_error_text(
                        "generic",
                        "An error occurred. A manager will follow up.",
                    )
                )
            ],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason=f"AGENT_ERROR: {str(e)[:100]}"),
        )


_offer_circuit_breaker = get_circuit_breaker(
    "pydantic_ai_offer_agent",
    failure_threshold=3,
    recovery_timeout=60.0,
)


async def run_offer(
    message: str,
    deps: AgentDeps,
    message_history: list[Any] | None = None,
) -> OfferResponse:
    """
    Run offer agent and return structured response with deliberation.
    """
    import asyncio

    # Check circuit breaker before attempting LLM call
    if not _offer_circuit_breaker.can_execute():
        logger.warning(
            "Circuit breaker OPEN for offer agent (session %s). Escalating.",
            deps.session_id,
        )
        return OfferResponse(
            event="escalation",
            messages=[
                MessageItem(
                    content=_get_error_text(
                        "overload",
                        "System temporarily unavailable. A manager will follow up.",
                    )
                )
            ],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason="CIRCUIT_BREAKER_OPEN"),
        )

    agent = get_offer_agent()

    try:
        result = await asyncio.wait_for(
            agent.run(
                message,
                deps=deps,
                message_history=message_history,
            ),
            timeout=45,
        )
        _offer_circuit_breaker.record_success()
        return result.output

    except Exception as e:
        logger.exception("Offer agent error: %s", e)
        _offer_circuit_breaker.record_failure(e)
        return OfferResponse(
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
