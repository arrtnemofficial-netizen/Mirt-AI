"""
Upsell Node - Additional sales opportunity.
==========================================
After payment confirmation, offer complementary products.
Uses run_support directly with upsell context.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.support_agent import run_support
from src.core.state_machine import State
from src.services.observability import log_agent_step, track_metric


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents.pydantic.models import SupportResponse


logger = logging.getLogger(__name__)


async def upsell_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,  # Kept for signature compatibility
) -> dict[str, Any]:
    """
    Offer additional products after payment confirmation.

    This is a soft upsell - suggest, don't push.

    Args:
        state: Current conversation state
        runner: IGNORED - uses run_support directly

    Returns:
        State update with upsell response
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # Get user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message
    user_message = extract_user_message(state.get("messages", []))
    if not user_message:
        user_message = "Замовлення оформлено"

    # Get current order for context
    ordered_products = state.get("offered_products", []) or state.get("selected_products", [])

    # Create deps with upsell context
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_6_UPSELL.value
    deps.selected_products = ordered_products

    logger.info("Upsell node for session %s", session_id)

    try:
        # Call support agent with upsell context
        response: SupportResponse = await run_support(
            message=user_message,
            deps=deps,
            message_history=None,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000

        log_agent_step(
            session_id=session_id,
            state=State.STATE_6_UPSELL.value,
            intent=response.metadata.intent,
            event=response.event,
            latency_ms=latency_ms,
        )
        track_metric("upsell_node_latency_ms", latency_ms)
        track_metric("upsell_offered", 1, {"session_id": session_id})

        # Build assistant message from response
        assistant_content = "\n".join(m.content for m in response.messages)

        return {
            "current_state": State.STATE_6_UPSELL.value,
            "messages": [{"role": "assistant", "content": assistant_content}],
            "metadata": response.metadata.model_dump(),
            "agent_response": response.model_dump(),
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
        }

    except Exception as e:
        logger.exception("Upsell node failed for session %s: %s", session_id, e)

        # Non-critical - just skip upsell on error
        return {
            "current_state": State.STATE_7_END.value,
            "step_number": state.get("step_number", 0) + 1,
        }
