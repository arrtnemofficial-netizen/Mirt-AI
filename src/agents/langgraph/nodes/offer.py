"""
Offer Node - Product presentation.
==================================
Presents product offer with price and details.
This is where we close the sale.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from src.core.state_machine import State
from src.services.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


async def offer_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """
    Present product offer with price and details.

    This node:
    1. Takes selected products from previous nodes
    2. Formats compelling offer with prices
    3. Asks if client wants to proceed to payment

    Args:
        state: Current conversation state
        runner: LLM runner function

    Returns:
        State update with offer response
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # Get products to offer
    selected_products = state.get("selected_products", [])

    # Build offer context
    if selected_products:
        products_context = _format_products_for_offer(selected_products)
    else:
        products_context = "Немає вибраних товарів. Допоможи клієнту обрати."

    # Prepare metadata
    prepared_metadata = {
        **state.get("metadata", {}),
        "current_state": State.STATE_4_OFFER.value,
        "selected_products": selected_products,
        "system_instructions": (
            f"Зроби КОНКРЕТНУ пропозицію з ціною!\n\n"
            f"ТОВАРИ:\n{products_context}\n\n"
            "ІНСТРУКЦІЇ:\n"
            "1. Покажи товар чітко: назва, ціна, розміри\n"
            "2. Вкажи переваги (якість, матеріал)\n"
            "3. Запитай: 'Оформлюємо замовлення?' або 'Беремо?'\n"
            "4. НЕ згадуй технічні деталі (артикули, ID)\n"
            "5. Будь ентузіастичною, але не нав'язливою"
        ),
    }

    try:
        response = await runner(state.get("messages", []), prepared_metadata)

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

        return {
            "current_state": State.STATE_4_OFFER.value,
            "messages": [{"role": "assistant", "content": response.model_dump_json()}],
            "metadata": response.metadata.model_dump(),
            "offered_products": offered_products,
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
        }

    except Exception as e:
        logger.error("Offer node failed for session %s: %s", session_id, e)

        return {
            "last_error": str(e),
            "tool_errors": state.get("tool_errors", []) + [f"Offer error: {e}"],
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
