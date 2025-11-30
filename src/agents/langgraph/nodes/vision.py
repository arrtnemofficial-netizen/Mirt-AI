"""
Vision Node - Photo processing.
===============================
Handles image identification and product matching.
Uses run_vision directly (NOT through generic runner).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.vision_agent import run_vision
from src.core.state_machine import State
from src.services.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


async def vision_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,  # Kept for signature compatibility
) -> dict[str, Any]:
    """
    Process photo and identify product.

    This node:
    1. Extracts user message and image_url from state
    2. Calls run_vision (PydanticAI vision agent) DIRECTLY
    3. Extracts identified products
    4. Updates state with results

    Args:
        state: Current conversation state
        runner: IGNORED - uses run_vision directly

    Returns:
        State update with identified products
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # Get user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message
    user_message = extract_user_message(state.get("messages", []))

    if not user_message:
        user_message = "Аналіз фото"  # Default for photo-only messages

    # Create deps with image context
    deps = create_deps_from_state(state)
    # Ensure image flags are set
    deps.has_image = True
    deps.image_url = state.get("image_url") or state.get("metadata", {}).get("image_url")
    deps.current_state = State.STATE_2_VISION.value

    logger.info(
        "Vision node processing for session %s, image_url=%s",
        session_id,
        deps.image_url[:50] if deps.image_url else "None",
    )

    try:
        # Call PydanticAI vision agent DIRECTLY (not through generic runner!)
        response = await run_vision(
            message=user_message,
            deps=deps,
            message_history=None,
        )

        # DETAILED LOGGING: What did the agent return?
        logger.info(
            "Vision agent response for session %s: reply=%s, confidence=%.2f, "
            "identified=%s, alternatives=%d",
            session_id,
            response.reply_to_user[:100] if response.reply_to_user else "None",
            response.confidence,
            response.identified_product.name if response.identified_product else "None",
            len(response.alternative_products),
        )

        # Extract products from VisionResponse
        selected_products = state.get("selected_products", [])
        if response.identified_product:
            selected_products = [response.identified_product.model_dump()]
            logger.info("Vision identified product: %s", response.identified_product.name)
        if response.alternative_products:
            selected_products.extend([p.model_dump() for p in response.alternative_products])
            logger.info("Vision alternatives: %s", [p.name for p in response.alternative_products])

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Log success
        log_agent_step(
            session_id=session_id,
            state=State.STATE_2_VISION.value,
            intent="PHOTO_IDENT",
            event="vision_complete",
            latency_ms=latency_ms,
            extra={
                "products_count": len(selected_products),
                "confidence": response.confidence,
                "needs_clarification": response.needs_clarification,
            },
        )
        track_metric("vision_node_latency_ms", latency_ms)

        # Build assistant message
        assistant_content = response.reply_to_user
        if response.clarification_question:
            assistant_content += f"\n\n{response.clarification_question}"

        return {
            "current_state": State.STATE_2_VISION.value,
            "messages": [{"role": "assistant", "content": assistant_content}],
            "selected_products": selected_products,
            "metadata": {
                **state.get("metadata", {}),
                "vision_confidence": response.confidence,
                "needs_clarification": response.needs_clarification,
            },
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
        }

    except Exception as e:
        logger.exception("Vision node failed for session %s: %s", session_id, e)

        return {
            "last_error": str(e),
            "tool_errors": state.get("tool_errors", []) + [f"Vision error: {e}"],
            "retry_count": state.get("retry_count", 0) + 1,
            "step_number": state.get("step_number", 0) + 1,
        }
