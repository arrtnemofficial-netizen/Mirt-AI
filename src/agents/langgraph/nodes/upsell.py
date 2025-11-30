"""
Upsell Node - Additional sales opportunity.
==========================================
After payment confirmation, offer complementary products.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from src.core.state_machine import State
from src.services.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


async def upsell_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """
    Offer additional products after payment confirmation.

    This is a soft upsell - suggest, don't push.

    Args:
        state: Current conversation state
        runner: LLM runner function

    Returns:
        State update with upsell response
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # Get current order for context
    ordered_products = state.get("offered_products", []) or state.get("selected_products", [])

    # Prepare upsell context
    prepared_metadata = {
        **state.get("metadata", {}),
        "current_state": State.STATE_6_UPSELL.value,
        "ordered_products": ordered_products,
        "system_instructions": (
            "Оплата підтверджена! Замовлення оформлено. "
            "Тепер М'ЯКО запропонуй додатковий товар:\n"
            "1. Подякуй за замовлення\n"
            "2. Запропонуй аксесуар або комплект (бантик, шкарпетки, пов'язка)\n"
            "3. Якщо клієнт відмовляється - подякуй і заверши ввічливо\n"
            "4. НЕ тисни, НЕ нав'язуй - один раз запропонував і все\n"
            "5. Нагадай про термін доставки (2-3 дні)"
        ),
    }

    try:
        response = await runner(state.get("messages", []), prepared_metadata)

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

        return {
            "current_state": State.STATE_6_UPSELL.value,
            "messages": [{"role": "assistant", "content": response.model_dump_json()}],
            "metadata": response.metadata.model_dump(),
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
        }

    except Exception as e:
        logger.error("Upsell node failed for session %s: %s", session_id, e)

        # Non-critical - just skip upsell on error
        return {
            "current_state": State.STATE_7_END.value,
            "step_number": state.get("step_number", 0) + 1,
        }
