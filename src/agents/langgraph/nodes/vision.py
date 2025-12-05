"""
Vision Node - Photo processing.
===============================
Handles image identification and product matching.
Uses run_vision directly (NOT through generic runner).

REFACTORED for clarity:
- _extract_products() — get products from VisionResponse
- _build_vision_messages() — build multi-bubble response
- vision_node() — main orchestrator (simple!)
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.vision_agent import run_vision
from src.core.state_machine import State
from src.services.observability import log_agent_step, track_metric

from .utils import has_assistant_reply, image_msg, text_msg


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents.pydantic.models import VisionResponse


logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS (extracted for clarity)
# =============================================================================


def _extract_products(
    response: VisionResponse,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract products from VisionResponse into state format."""
    products = list(existing)

    if response.identified_product:
        products = [response.identified_product.model_dump()]
        logger.info("Vision identified: %s", response.identified_product.name)

    if response.alternative_products:
        products.extend([p.model_dump() for p in response.alternative_products])
        logger.info("Vision alternatives: %d", len(response.alternative_products))

    return products


def _build_vision_messages(
    response: VisionResponse,
    previous_messages: list[Any],
) -> list[dict[str, str]]:
    """
    Build multi-bubble assistant response from VisionResponse.

    Message order:
    1. Greeting (if first message)
    2. Main vision reply
    3. Product highlight + photo
    4. Clarification question (if needed)
    """
    messages: list[dict[str, str]] = []

    # 1. Greeting if first interaction
    if not has_assistant_reply(previous_messages):
        messages.append(text_msg("Вітаю 🎀 З вами Ольга. Дякую за фото!"))

    # 2. Main vision response
    if response.reply_to_user:
        messages.append(text_msg(response.reply_to_user.strip()))

    # 3. Product highlight
    product = response.identified_product
    if product:
        # Build product description
        parts = [f"Це наш {product.name}"]
        if product.color:
            parts.append(f"у кольорі {product.color}")
        if product.price:
            parts.append(f"— {product.price} грн")
        messages.append(text_msg(" ".join(parts) + "."))

        # Add product photo
        if product.photo_url:
            messages.append(image_msg(product.photo_url))

    # 4. Clarification
    if response.clarification_question:
        messages.append(text_msg(response.clarification_question.strip()))
    elif response.needs_clarification:
        messages.append(text_msg(
            "Який розмір потрібен? Підкажіть, будь ласка, зріст дитини 🤍"
        ))

    # 5. Fallback
    if not messages:
        messages.append(text_msg(
            "Зчитала фото. Готова допомогти з розміром чи деталями 🤍"
        ))

    return messages


# =============================================================================
# MAIN NODE
# =============================================================================


async def vision_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,  # Kept for signature compatibility
) -> dict[str, Any]:
    """
    Process photo and identify product.

    This node:
    1. Extracts user message and image_url from state
    2. Calls run_vision (PydanticAI vision agent)
    3. Builds multi-bubble response using helper functions
    4. Updates state with results

    Args:
        state: Current conversation state
        runner: IGNORED - uses run_vision directly

    Returns:
        State update with identified products
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    messages = state.get("messages", [])

    # Extract user message
    from .utils import extract_user_message
    user_message = extract_user_message(messages) or "Аналіз фото"

    # Build deps with image context
    deps = create_deps_from_state(state)
    deps.has_image = True
    deps.image_url = state.get("image_url") or state.get("metadata", {}).get("image_url")
    deps.current_state = State.STATE_2_VISION.value

    logger.info(
        "Vision node: session=%s, image=%s",
        session_id,
        deps.image_url[:50] if deps.image_url else "None",
    )

    try:
        # Call vision agent
        response = await run_vision(message=user_message, deps=deps)

        # Log response
        logger.info(
            "Vision result: confidence=%.2f, product=%s",
            response.confidence,
            response.identified_product.name if response.identified_product else "None",
        )

        # Extract products and build messages using helpers
        selected_products = _extract_products(
            response, state.get("selected_products", [])
        )
        assistant_messages = _build_vision_messages(response, messages)

        # Metrics
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_agent_step(
            session_id=session_id,
            state=State.STATE_2_VISION.value,
            intent="PHOTO_IDENT",
            event="vision_complete",
            latency_ms=latency_ms,
            extra={
                "products_count": len(selected_products),
                "confidence": response.confidence,
            },
        )
        track_metric("vision_node_latency_ms", latency_ms)

        return {
            "current_state": State.STATE_2_VISION.value,
            "messages": assistant_messages,
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
        logger.exception("Vision node failed: %s", e)
        return {
            "last_error": str(e),
            "tool_errors": [*state.get("tool_errors", []), f"Vision error: {e}"],
            "retry_count": state.get("retry_count", 0) + 1,
            "step_number": state.get("step_number", 0) + 1,
        }
