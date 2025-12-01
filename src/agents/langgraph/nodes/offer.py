"""
Offer Node - Product presentation.
==================================
Presents product offer with price and details.
This is where we close the sale.
Uses run_support directly with offer context.
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


async def offer_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,  # Kept for signature compatibility
) -> dict[str, Any]:
    """
    Present product offer with price and details.

    This node:
    1. Takes selected products from previous nodes
    2. Calls run_support with offer context
    3. Asks if client wants to proceed to payment

    Args:
        state: Current conversation state
        runner: IGNORED - uses run_support directly

    Returns:
        State update with offer response
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # Get user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message
    user_message = extract_user_message(state.get("messages", []))

    if not user_message:
        user_message = "Покажи товар"

    # Get products to offer
    selected_products = state.get("selected_products", [])

    # Create deps with offer context
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_4_OFFER.value
    deps.selected_products = selected_products

    logger.info(
        "Offer node for session %s, products=%d",
        session_id,
        len(selected_products),
    )

    try:
        # Call support agent with offer context
        response: SupportResponse = await run_support(
            message=user_message,
            deps=deps,
            message_history=None,
        )

        # Store offered products for tracking
        offered_products = selected_products.copy()

        latency_ms = (time.perf_counter() - start_time) * 1000

        log_agent_step(
            session_id=session_id,
            state=State.STATE_4_OFFER.value,
            intent=response.metadata.intent,
            event=response.event,
            latency_ms=latency_ms,
            extra={"offered_products": len(offered_products)},
        )
        track_metric("offer_node_latency_ms", latency_ms)

        # Build assistant message from response
        assistant_content = "\n".join(m.content for m in response.messages)

        return {
            "current_state": State.STATE_4_OFFER.value,
            "messages": [{"role": "assistant", "content": assistant_content}],
            "metadata": response.metadata.model_dump(),
            "offered_products": offered_products,
            "agent_response": response.model_dump(),
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
        }

    except Exception as e:
        logger.exception("Offer node failed for session %s: %s", session_id, e)

        return {
            "last_error": str(e),
            "tool_errors": [*state.get("tool_errors", []), f"Offer error: {e}"],
            "retry_count": state.get("retry_count", 0) + 1,
            "step_number": state.get("step_number", 0) + 1,
        }


def _format_products_for_offer(products: list[dict[str, Any]]) -> str:
    """Format products list for LLM context."""
    lines = []
    for i, p in enumerate(products[:5], 1):  # Limit to 5 products
        name = p.get("name", "Товар")
        price = p.get("price", 0)
        sizes = p.get("sizes", [])
        colors = p.get("colors", [])

        line = f"{i}. {name} - {price} грн"
        if sizes:
            line += f" (розміри: {', '.join(str(s) for s in sizes[:5])})"
        if colors:
            line += f" (кольори: {', '.join(colors[:3])})"
        lines.append(line)

    return "\n".join(lines) if lines else "Товари не вибрано"
