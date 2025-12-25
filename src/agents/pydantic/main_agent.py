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
    """Get or create OpenAI GPT-5.1 model (lazy initialization)."""
    global _model
    if _model is None:
        api_key = settings.OPENAI_API_KEY.get_secret_value()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required. OpenRouter support has been removed.")
        
        base_url = "https://api.openai.com/v1"
        model_name = settings.LLM_MODEL_GPT  # GPT-5.1 only

        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        provider = OpenAIProvider(openai_client=client)
        _model = OpenAIModel(model_name, provider=provider)
    return _model


def _get_base_prompt() -> str:
    """Get system prompt (lazy load).
    
    Architecture:
    - base_identity: CORE rules (immutable, universal)
    - system.main: DOMAIN CONTEXT (who you are, mission, tone, style)
    - main.main: DOMAIN LOGIC (how to work with products, format, business rules)
    """
    base_identity = registry.get("system.base_identity").content
    domain_context = registry.get("system.main").content
    domain_logic = registry.get("main.main").content
    return f"{base_identity}\n\n{domain_context}\n\n{domain_logic}"


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
    """Load size mapping from SSOT YAML.
    
    FAIL-FAST: Raises RuntimeError if SSOT file is missing or invalid.
    This ensures we never use stale hardcoded fallback data.
    """
    path = (
        Path(__file__).parent.parent.parent.parent
        / "data"
        / "prompts"
        / "system"
        / "size_guide.yaml"
    )

    if not path.exists():
        raise RuntimeError(
            f"CRITICAL: SSOT file missing: {path}. "
            "Size mapping is required for agent operation. "
            "Ensure data/prompts/system/size_guide.yaml exists in deployment."
        )

    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError(
                f"CRITICAL: Invalid YAML structure in {path}. "
                "Expected dict with 'size_mapping' and 'border_sizes' keys."
            )

        size_mapping = data.get("size_mapping", [])
        border_sizes = data.get("border_sizes", {})
        
        if not isinstance(size_mapping, list) or not size_mapping:
            raise RuntimeError(
                f"CRITICAL: Invalid 'size_mapping' in {path}. "
                "Expected non-empty list of size range dictionaries."
            )
        
        if not isinstance(border_sizes, dict):
            raise RuntimeError(
                f"CRITICAL: Invalid 'border_sizes' in {path}. "
                "Expected dict mapping height (int) to size string."
            )

        return size_mapping, border_sizes
        
    except yaml.YAMLError as e:
        raise RuntimeError(
            f"CRITICAL: Failed to parse YAML in {path}: {e}. "
            "Check file syntax and encoding (must be UTF-8)."
        ) from e
    except Exception as e:
        raise RuntimeError(
            f"CRITICAL: Failed to load size mapping from {path}: {e}. "
            "This is a required SSOT file for agent operation."
        ) from e




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

    # Optional tracing span (Logfire/OpenTelemetry). Keep None when not configured.
    span = None

    # Check circuit breaker before attempting LLM call
    if not _llm_circuit_breaker.can_execute():
        logger.warning(
            "Circuit breaker OPEN for main agent (session %s). Escalating.",
            deps.session_id,
        )
        # Escalation always means dialog completion, so set STATE_7_END to match COMPLETED phase
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
                current_state="STATE_7_END",  # Escalation = COMPLETED phase = STATE_7_END
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

        # Track token usage if available (GPT 5.1 only)
        try:
            from src.services.core.observability import track_token_usage
            from src.workers.tasks.llm_usage import calculate_cost
            
            # PydanticAI result structure for GPT 5.1:
            # result.snapshot.usage.input_tokens / output_tokens
            # result.snapshot.model_name
            tokens_input = 0
            tokens_output = 0
            model = "gpt-5.1"  # Default to GPT 5.1
            
            if hasattr(result, "snapshot") and result.snapshot:
                snapshot = result.snapshot
                
                # Get model name from snapshot
                if hasattr(snapshot, "model_name") and snapshot.model_name:
                    model = snapshot.model_name
                elif hasattr(snapshot, "model") and snapshot.model:
                    model = str(snapshot.model)
                
                # Normalize model name to "gpt-5.1" if it's GPT 5.1 variant
                if "gpt-5" in model.lower() or "5.1" in model:
                    model = "gpt-5.1"
                
                # Get usage info from snapshot
                if hasattr(snapshot, "usage") and snapshot.usage:
                    usage = snapshot.usage
                    # Try different attribute names for token counts
                    tokens_input = (
                        getattr(usage, "input_tokens", None) or
                        getattr(usage, "prompt_tokens", None) or
                        getattr(usage, "tokens_input", None) or
                        0
                    )
                    tokens_output = (
                        getattr(usage, "output_tokens", None) or
                        getattr(usage, "completion_tokens", None) or
                        getattr(usage, "tokens_output", None) or
                        0
                    )
                # Alternative: check if usage is a dict
                elif isinstance(snapshot.usage, dict):
                    usage_dict = snapshot.usage
                    tokens_input = usage_dict.get("input_tokens") or usage_dict.get("prompt_tokens") or 0
                    tokens_output = usage_dict.get("output_tokens") or usage_dict.get("completion_tokens") or 0
                
                # Track if we have valid token counts
                if tokens_input > 0 or tokens_output > 0:
                    cost = calculate_cost(model, tokens_input, tokens_output)
                    track_token_usage(
                        tokens_input=tokens_input,
                        tokens_output=tokens_output,
                        model=model,
                        session_id=deps.session_id,
                        cost_usd=float(cost),
                    )
                    
                    # Dispatch to background worker for DB recording
                    from src.workers.dispatcher import dispatch_llm_usage
                    dispatch_llm_usage(
                        user_id=None,  # Can be extracted from deps if needed
                        model=model,
                        tokens_input=tokens_input,
                        tokens_output=tokens_output,
                        session_id=deps.session_id,
                    )
                else:
                    logger.debug(
                        "[TOKEN_TRACKING] No token usage found in snapshot for GPT 5.1. "
                        "Snapshot structure: %s",
                        type(snapshot).__name__ if snapshot else "None",
                    )
        except Exception as e:
            # Don't fail the request if token tracking fails
            logger.debug("[TOKEN_TRACKING] Failed to track tokens for GPT 5.1: %s", e)

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
        # Escalation always means dialog completion, so set STATE_7_END to match COMPLETED phase
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
                current_state="STATE_7_END",  # Escalation = COMPLETED phase = STATE_7_END
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L1",
            ),
            escalation=EscalationInfo(reason="LLM_TIMEOUT"),
        )

    except CircuitBreakerOpenError:
        # Re-raise circuit breaker errors (shouldn't happen here, but handle gracefully)
        logger.error("Circuit breaker error for session %s", deps.session_id)
        # Escalation always means dialog completion, so set STATE_7_END to match COMPLETED phase
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
                current_state="STATE_7_END",  # Escalation = COMPLETED phase = STATE_7_END
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason="CIRCUIT_BREAKER_OPEN"),
        )

    except Exception as e:
        error_str = str(e).lower()
        error_msg = str(e)
        
        # Special handling for quota exceeded (429)
        if "429" in error_msg or "quota" in error_str or "insufficient_quota" in error_str:
            logger.error("Support agent quota exceeded for session %s: %s", deps.session_id, error_msg[:200])
            if span:
                span.set_attribute("error", True)
                span.set_attribute("error_type", "QuotaExceeded")
                span.set_attribute("error_message", error_msg[:200])
            _llm_circuit_breaker.record_failure(e)
            # Escalation always means dialog completion, so set STATE_7_END to match COMPLETED phase
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
                    current_state="STATE_7_END",  # Escalation = COMPLETED phase = STATE_7_END
                    intent="UNKNOWN_OR_EMPTY",
                    escalation_level="L2",
                ),
                escalation=EscalationInfo(reason="QUOTA_EXCEEDED"),
            )
        
        logger.exception("Support agent error: %s", e)
        if span:
            span.set_attribute("error", True)
            span.set_attribute("error_type", type(e).__name__)
            span.set_attribute("error_message", str(e)[:200])
        _llm_circuit_breaker.record_failure(e)
        # Escalation always means dialog completion, so set STATE_7_END to match COMPLETED phase
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
                current_state="STATE_7_END",  # Escalation = COMPLETED phase = STATE_7_END
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
        # Escalation always means dialog completion, so set STATE_7_END to match COMPLETED phase
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
                current_state="STATE_7_END",  # Escalation = COMPLETED phase = STATE_7_END
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
        # Escalation always means dialog completion, so set STATE_7_END to match COMPLETED phase
        return OfferResponse(
            event="escalation",
            messages=[MessageItem(content=_get_error_response())],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state="STATE_7_END",  # Escalation = COMPLETED phase = STATE_7_END
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason=f"AGENT_ERROR: {str(e)[:100]}"),
        )
