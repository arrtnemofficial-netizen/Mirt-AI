"""
Vision Node - Photo processing.
===============================
Handles image identification and product matching.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from src.core.state_machine import State
from src.services.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


async def vision_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """
    Process photo and identify product.

    This node:
    1. Prepares image context for LLM
    2. Calls LLM with vision instructions
    3. Extracts identified products
    4. Updates state with results

    Args:
        state: Current conversation state
        runner: LLM runner function (from pydantic_agent)

    Returns:
        State update with identified products
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # Prepare metadata with vision context
    prepared_metadata = {
        **state.get("metadata", {}),
        "current_state": State.STATE_2_VISION.value,
        "has_image": True,
        "system_instructions": (
            "ВАЖЛИВО: Користувач надіслав ФОТО! "
            "1. Проаналізуй фото та визнач товар з EMBEDDED CATALOG. "
            "2. Якщо знайшов товар - ОДРАЗУ дай ціну та запропонуй розмір. "
            "3. Intent має бути PHOTO_IDENT. "
            "4. Не питай 'що вас цікавить' - відповідай конкретно про товар на фото! "
            "5. Якщо товар не знайдено - скажи чесно і запропонуй альтернативи."
        ),
    }

    # Call LLM
    try:
        response = await runner(state.get("messages", []), prepared_metadata)

        # Extract products from response
        selected_products = []
        if response.products:
            selected_products = [p.model_dump() for p in response.products]

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Log success
        log_agent_step(
            session_id=session_id,
            state=State.STATE_2_VISION.value,
            intent="PHOTO_IDENT",
            event=response.event,
            latency_ms=latency_ms,
            extra={"products_count": len(selected_products)},
        )
        track_metric("vision_node_latency_ms", latency_ms)

        return {
            "current_state": State.STATE_2_VISION.value,
            "messages": [{"role": "assistant", "content": response.model_dump_json()}],
            "metadata": response.metadata.model_dump(),
            "selected_products": selected_products,
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,  # Clear any previous error
        }

    except Exception as e:
        logger.error("Vision node failed for session %s: %s", session_id, e)

        return {
            "last_error": str(e),
            "tool_errors": state.get("tool_errors", []) + [f"Vision error: {e}"],
            "retry_count": state.get("retry_count", 0) + 1,
            "step_number": state.get("step_number", 0) + 1,
        }
