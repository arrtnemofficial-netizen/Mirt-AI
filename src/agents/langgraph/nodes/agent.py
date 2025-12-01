"""
Agent Node - Main LLM processing.
=================================
General-purpose agent for discovery, size/color questions.

Uses PydanticAI agents with:
- deps_type for proper dependency injection
- output_type for structured output (no manual parsing!)
- @agent.system_prompt for dynamic context
- @agent.tool for tools with DI
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

# PydanticAI imports
from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.models import SupportResponse
from src.agents.pydantic.support_agent import run_support
from src.core.state_machine import State
from src.services.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


async def agent_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """
    General agent node using PydanticAI with proper DI.

    This is the main workhorse node that handles most conversations.
    Uses support_agent with:
    - AgentDeps for dependency injection
    - SupportResponse for structured output

    Args:
        state: Current conversation state
        runner: Legacy runner (ignored, uses PydanticAI)

    Returns:
        State update with structured response
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    current_state = state.get("current_state", State.STATE_0_INIT.value)

    # Get user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message
    user_message = extract_user_message(state.get("messages", []))

    if not user_message:
        return {
            "step_number": state.get("step_number", 0) + 1,
        }

    # Create deps from state (proper DI!)
    deps = create_deps_from_state(state)

    try:
        # Call PydanticAI agent with proper DI
        # Returns STRUCTURED SupportResponse (OUTPUT_CONTRACT format)
        response: SupportResponse = await run_support(
            message=user_message,
            deps=deps,
            message_history=None,
        )

        # DETAILED LOGGING: What did the agent return?
        first_msg = response.messages[0].content[:100] if response.messages else "None"
        logger.info(
            "Agent response for session %s: event=%s, state=%s->%s, intent=%s, "
            "products=%d, msg=%s",
            session_id,
            response.event,
            current_state,
            response.metadata.current_state,
            response.metadata.intent,
            len(response.products),
            first_msg,
        )

        # Extract from OUTPUT_CONTRACT structure
        new_state_str = response.metadata.current_state
        intent = response.metadata.intent
        is_escalation = response.event == "escalation"

        # Extract products (already typed from CATALOG!)
        selected_products = state.get("selected_products", [])
        if response.products:
            selected_products = [p.model_dump() for p in response.products]
            logger.info("Agent found products: %s", [p.name for p in response.products])

        # Build assistant message (OUTPUT_CONTRACT format)
        assistant_content = {
            "event": response.event,
            "messages": [m.model_dump() for m in response.messages],
            "products": [p.model_dump() for p in response.products],
            "metadata": response.metadata.model_dump(),
        }

        if response.escalation:
            assistant_content["escalation"] = response.escalation.model_dump()

        if response.reasoning:
            assistant_content["reasoning"] = response.reasoning

        # Persist structured response for downstream consumers (Telegram, ManyChat, etc.)
        agent_response_payload = response.model_dump()

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Log
        log_agent_step(
            session_id=session_id,
            state=new_state_str,
            intent=intent,
            event=response.event,
            latency_ms=latency_ms,
            extra={
                "old_state": current_state,
                "products_count": len(selected_products),
            },
        )
        track_metric("agent_node_latency_ms", latency_ms)

        # Update customer data if extracted
        metadata_update = state.get("metadata", {}).copy()
        metadata_update["current_state"] = new_state_str
        metadata_update["intent"] = intent
        if response.customer_data:
            if response.customer_data.name:
                metadata_update["customer_name"] = response.customer_data.name
            if response.customer_data.phone:
                metadata_update["customer_phone"] = response.customer_data.phone
            if response.customer_data.city:
                metadata_update["customer_city"] = response.customer_data.city
            if response.customer_data.nova_poshta:
                metadata_update["customer_nova_poshta"] = response.customer_data.nova_poshta

        return {
            "current_state": new_state_str,
            "detected_intent": intent,
            "messages": [{"role": "assistant", "content": str(assistant_content)}],
            "metadata": metadata_update,
            "selected_products": selected_products,
            "should_escalate": is_escalation,
            "escalation_reason": response.escalation.reason if response.escalation else None,
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
            "agent_response": agent_response_payload,
        }

    except Exception as e:
        logger.error("Agent node failed for session %s: %s", session_id, e)

        return {
            "last_error": str(e),
            "tool_errors": state.get("tool_errors", []) + [f"Agent error: {e}"],
            "retry_count": state.get("retry_count", 0) + 1,
            "step_number": state.get("step_number", 0) + 1,
        }


def _get_instructions_for_intent(intent: str, state: dict[str, Any]) -> str:
    """Get context-specific instructions based on detected intent."""

    instructions = {
        "GREETING_ONLY": (
            "Привітай клієнта тепло, як MIRT_UA менеджер Ольга. "
            "Запитай чим можеш допомогти. "
            "Не перевантажуй інформацією - будь лаконічною."
        ),
        "DISCOVERY_OR_QUESTION": (
            "Клієнт шукає товар або має питання. "
            "Знайди відповідні товари в EMBEDDED CATALOG. "
            "Покажи варіанти з цінами та характеристиками. "
            "Якщо потрібно - запитай уточнення (зріст, вік, колір)."
        ),
        "SIZE_HELP": (
            "Клієнт питає про розмір. "
            "Дай КОНКРЕТНУ відповідь з розмірної сітки. "
            "Якщо знаєш зріст - підбери розмір. "
            "Якщо є вибраний товар - переходь до пропозиції!"
        ),
        "COLOR_HELP": (
            "Клієнт питає про колір. "
            "Покажи доступні кольори для товару. "
            "Якщо товар є в потрібному кольорі - підтверди. "
            "Якщо немає - запропонуй альтернативи."
        ),
        "THANKYOU_SMALLTALK": (
            "Клієнт подякував або веде світську бесіду. "
            "Відповідай тепло, але коротко. "
            "Запропонуй допомогу, якщо потрібно."
        ),
    }

    # Add product context if available
    products = state.get("selected_products", [])
    if products:
        product_names = ", ".join(p.get("name", "товар") for p in products[:3])
        base = instructions.get(intent, instructions["DISCOVERY_OR_QUESTION"])
        return f"{base}\n\nУ діалозі вже є товари: {product_names}."

    return instructions.get(intent, instructions["DISCOVERY_OR_QUESTION"])
