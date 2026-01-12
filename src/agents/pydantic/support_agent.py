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

from pydantic_ai import Agent, RunContext, RunUsage

from src.conf.config import settings
from src.core.human_responses import get_human_response
from src.core.prompt_registry import registry

from .shared.model_factory import build_pydantic_model, get_ironclad_model_settings
from .shared.catalog_tools import search_products_tool
from .shared.payment_prompts import add_payment_requisites

from .alerting import record_agent_error
from .circuit_breaker import get_support_circuit_breaker
from .deps import AgentDeps
from .exceptions import AgentError, AgentLLMError, AgentNetworkError, AgentTimeoutError
from .metrics import track_agent_metrics
from .models import (
    EscalationInfo,
    MessageItem,
    ResponseMetadata,
    SupportResponse,
)
from .retry import retry_agent_call
from .tracing import trace_agent_call
from .validation import validate_agent_deps, validate_message


logger = logging.getLogger(__name__)


def _get_timeout_response() -> str:
    """Get human-like timeout response."""
    return get_human_response("timeout")


def _get_error_response() -> str:
    """Get human-like error response."""
    return get_human_response("error")


_agent: Agent[AgentDeps, SupportResponse] | None = None


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
    """
    Add image context instructions if image present.
    
    CRITICAL: This agent is TEXT-ONLY. It does NOT analyze photos.
    Photo identification is handled by vision_node. This function only
    provides context about the photo's purpose in the conversation.
    """
    if not ctx.deps.has_image:
        return ""

    # Get image context from metadata (set by photo_purpose detection)
    metadata = getattr(ctx.deps, "metadata", {}) or {}
    image_context = metadata.get("image_context", "unknown")
    current_state = ctx.deps.current_state

    # CRITICAL: Never instruct this agent to analyze photos
    # Photos are analyzed by vision_node, not this text-only agent

    if image_context == "product_identification" or image_context == "explicit_new_product":
        # This should not happen - if photo is for product identification,
        # it should have been routed to vision_node, not agent_node
        # But if it did reach here, just acknowledge the photo exists
        return """
--- ФОТО ВІД КЛІЄНТА ---
ВАЖЛИВО: Користувач надіслав ФОТО, але це має оброблятись через vision_node.
Якщо ти бачиш це повідомлення - це помилка роутингу.
Продовжуй діалог в контексті поточної фази, але НЕ намагайся аналізувати фото.
"""
    elif image_context == "payment":
        # Photo is payment proof - handled by payment node
        return """
--- ФОТО ВІД КЛІЄНТА (ПЛАТЕЖ) ---
Фото може бути квитанцією оплати. Обробляється в payment_node.
"""
    else:
        # Photo in ongoing conversation: handle in current phase context
        return """
--- ФОТО ВІД КЛІЄНТА (КОНТЕКСТ) ---
ВАЖЛИВО: Користувач надіслав ФОТО в контексті поточної фази!
1. Фото НЕ для ідентифікації товару (це має робити vision_node)
2. Оброби фото в контексті поточної фази (не як нове фото товару!)
3. Якщо це STATE_3_SIZE_COLOR - фото може бути для уточнення розміру/кольору
4. Якщо це STATE_5_PAYMENT_DELIVERY - фото може бути квитанцією оплати
5. НЕ встановлюй intent=PHOTO_IDENT - використовуй intent відповідно до фази
6. Продовжуй діалог в контексті поточної фази, не починай заново!
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
    from src.agents.langgraph.nodes.helpers.size_parsing import height_to_size
    from src.agents.langgraph.nodes.utils import get_size_recommendation_text

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





# =============================================================================
# REGISTRATION FUNCTIONS
# =============================================================================


def _register_dynamic_prompts(agent: Agent[AgentDeps, SupportResponse]) -> None:
    """Register dynamic system prompts with the agent."""
    agent.system_prompt(_add_manager_snippets)
    agent.system_prompt(add_payment_requisites)  # From shared module
    agent.system_prompt(_add_state_context)
    agent.system_prompt(_add_memory_context)  # Titans-like memory context
    agent.system_prompt(_add_image_context)
    agent.system_prompt(_add_state_instructions)


def _register_tools(agent: Agent[AgentDeps, SupportResponse]) -> None:
    """Register tools with the agent using decorator syntax."""
    agent.tool(name="get_size_recommendation")(_get_size_recommendation)
    agent.tool(name="check_customer_data")(_check_customer_data)
    agent.tool(name="get_order_summary")(_get_order_summary)
    # Use shared search_products_tool without SKU for support agent
    async def _search_products_wrapper(ctx: RunContext[AgentDeps], query: str, category: str | None = None) -> str:
        return await search_products_tool(ctx, query, category, include_sku=False)
    agent.tool(name="search_products")(_search_products_wrapper)


# =============================================================================
# AGENT FACTORY (Lazy initialization)
# =============================================================================


def get_support_agent() -> Agent[AgentDeps, SupportResponse]:
    """Get or create the support agent (lazy initialization)."""
    global _agent
    if _agent is None:
        # ЗАЛІЗОБЕТОННО: Use ironclad model settings
        model_settings = get_ironclad_model_settings()
        
        _agent = Agent(  # type: ignore[call-overload]
            build_pydantic_model(agent_name="support"),
            deps_type=AgentDeps,
            output_type=SupportResponse,  # Changed from result_type (PydanticAI 1.23+)
            system_prompt=_get_base_prompt(),
            retries=2,
            model_settings=model_settings,
        )
        _register_dynamic_prompts(_agent)
        _register_tools(_agent)

    return _agent


# =============================================================================
# RUNNER FUNCTION (for LangGraph nodes)
# =============================================================================


@trace_agent_call(agent_name="support")
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
    import time

    from src.services.observability.llm_usage_logger import log_llm_usage_best_effort

    # Validate inputs
    validate_agent_deps(deps, "support")
    message = validate_message(message)

    agent = get_support_agent()

    # Track latency and result for logging
    start_time = time.perf_counter()
    result = None
    response: SupportResponse | None = None
    success = True
    error_message: str | None = None
    tokens_input = 0
    tokens_output = 0
    # SENIOR-LEVEL: Get model name from actual model, not hardcoded fallback
    model_name: str | None = None
    # Use AI_MODEL as single source of truth
    support_model_name = settings.AI_MODEL

    try:
        # Wrap agent.run() to convert exceptions to specific types for retry logic
        async def _run_with_error_conversion():
            try:
                return await agent.run(
                    message,
                    deps=deps,
                    message_history=message_history,
                )
            except Exception as e:
                # Convert OpenAI/network errors to specific exceptions for retry logic
                error_str = str(e).lower()
                if "timeout" in error_str or "timed out" in error_str:
                    raise AgentTimeoutError(f"LLM timeout: {e}") from e
                elif "rate limit" in error_str or "429" in error_str:
                    raise AgentLLMError(f"Rate limit: {e}") from e
                elif "network" in error_str or "connection" in error_str:
                    raise AgentNetworkError(f"Network error: {e}") from e
                elif hasattr(e, "status_code"):
                    # HTTP errors
                    if e.status_code == 429:  # type: ignore
                        raise AgentLLMError(f"Rate limit (429): {e}") from e
                    elif e.status_code >= 500:  # type: ignore
                        raise AgentNetworkError(f"Server error ({e.status_code}): {e}") from e  # type: ignore
                    else:
                        raise AgentLLMError(f"API error: {e}") from e
                else:
                    # Re-raise as-is for other exceptions
                    raise

        # Apply retry logic to _run_with_error_conversion
        @retry_agent_call(max_retries=3, retry_on=(AgentNetworkError, AgentLLMError))
        async def _run_with_retry():
            return await _run_with_error_conversion()

        # Apply circuit breaker
        circuit_breaker = get_support_circuit_breaker()
        result = await asyncio.wait_for(
            circuit_breaker.call(_run_with_retry),
            timeout=45,  # Reduced to cap max response time
        )

        # result.output is the typed output (SupportResponse)
        # Note: output_type param (not result_type) but result.output (not result.response)
        response = result.output

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

        # SENIOR-LEVEL: Fallback to actual support model from settings, not hardcoded
        if not model_name:
            model_name = support_model_name

        return response

    except (TimeoutError, AgentTimeoutError) as e:
        success = False
        error_message = "LLM_TIMEOUT"
        logger.error("Support agent timeout for session %s: %s", deps.session_id, e)
        record_agent_error("support", "timeout")
        response = SupportResponse(
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
        return response

    except AgentLLMError as e:
        success = False
        error_message = f"LLM_ERROR: {str(e)[:100]}"
        logger.error("Support agent LLM error for session %s: %s", deps.session_id, e)
        record_agent_error("support", "llm_error")
        response = SupportResponse(
            event="escalation",
            messages=[MessageItem(content=_get_error_response())],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason=error_message),
        )
        return response

    except AgentNetworkError as e:
        success = False
        error_message = f"NETWORK_ERROR: {str(e)[:100]}"
        logger.error("Support agent network error for session %s: %s", deps.session_id, e)
        record_agent_error("support", "network_error")
        response = SupportResponse(
            event="escalation",
            messages=[MessageItem(content=_get_error_response())],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason=error_message),
        )
        return response

    except AgentError as e:
        success = False
        error_message = f"AGENT_ERROR: {str(e)[:100]}"
        logger.error("Support agent error for session %s: %s", deps.session_id, e)
        response = SupportResponse(
            event="escalation",
            messages=[MessageItem(content=_get_error_response())],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L2",
            ),
            escalation=EscalationInfo(reason=error_message),
        )
        return response

    except Exception as e:
        success = False
        error_message = f"UNKNOWN_ERROR: {str(e)[:100]}"
        logger.exception("Support agent unknown error for session %s: %s", deps.session_id, e)
        response = SupportResponse(
            event="escalation",
            messages=[MessageItem(content=_get_error_response())],
            metadata=ResponseMetadata(
                session_id=deps.session_id or "",
                current_state=deps.current_state or "STATE_0_INIT",
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="L3",
            ),
            escalation=EscalationInfo(reason=error_message),
        )
        return response

    finally:
        # Log usage (best-effort, non-blocking)
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # Track metrics
        track_agent_metrics(
            agent_name="support",
            success=success,
            latency_ms=latency_ms,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            error_type=error_message,
        )

        # Prepare minimal metadata
        metadata: dict[str, Any] = {}
        if response:
            metadata["current_state"] = response.metadata.current_state
            metadata["intent"] = response.metadata.intent
            metadata["dialog_phase"] = getattr(deps, "dialog_phase", None)
            metadata["has_image"] = bool(deps.has_image if hasattr(deps, "has_image") else False)
            if deps.has_image and hasattr(deps, "image_url") and deps.image_url:
                metadata["image_url"] = deps.image_url

        # Log asynchronously (fire-and-forget)
        asyncio.create_task(
            log_llm_usage_best_effort(
                session_id=deps.session_id,
                model=model_name or support_model_name,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                latency_ms=latency_ms,
                success=success,
                error_message=error_message,
                metadata=metadata if metadata else None,
                user_id=str(deps.user_id) if hasattr(deps, "user_id") and deps.user_id else None,
            )
        )
