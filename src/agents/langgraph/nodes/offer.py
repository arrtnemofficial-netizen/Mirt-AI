"""
Offer Node - Product presentation.
==================================
Presents product offer with price and details.
This is where we close the sale.

DELIBERATION FLOW:
1. Pre-validation: Check prices against DB before LLM call
2. LLM generates offer with deliberation (Customer/Business/Quality views)
3. Post-validation: If low confidence or price_mismatch → fallback
4. Return offer to customer

Uses run_main directly with offer context.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.main_agent import run_offer
from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.services.data.catalog_service import CatalogService
from src.services.core.observability import log_agent_step, track_metric


from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.services.data.catalog_service import CatalogService
from src.services.core.observability import log_agent_step, track_metric


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents.pydantic.models import OfferResponse
def _merge_product_fields(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge fields from incoming product into existing product, preserving truth."""
    merged = dict(existing)
    for key, new_value in incoming.items():
        if key == "price":
            if (isinstance(new_value, (int, float)) and new_value > 0) or key not in merged:
                merged[key] = new_value
            continue
        if key in {"size", "color", "photo_url", "description"}:
            if (isinstance(new_value, str) and new_value.strip()) or key not in merged:
                merged[key] = new_value
            continue
        merged[key] = new_value
    return merged


def _merge_products(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge product lists, preserving details like size/color/price."""
    by_id: dict[int, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for item in existing:
        pid = item.get("id")
        name = str(item.get("name") or "").strip().lower()
        if isinstance(pid, int) and pid > 0:
            by_id[pid] = item
        if name:
            by_name[name] = item

    merged_incoming: list[dict[str, Any]] = []
    for item in incoming:
        pid = item.get("id")
        name = str(item.get("name") or "").strip().lower()
        existing_item = None
        if isinstance(pid, int) and pid > 0:
            existing_item = by_id.get(pid)
        if existing_item is None and name:
            existing_item = by_name.get(name)
        merged_incoming.append(
            _merge_product_fields(existing_item or {}, item) if existing_item else item
        )

    return merged_incoming


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
        runner: IGNORED - uses run_main directly

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
        # =========================================================================
        # STEP 2: LLM CALL with deliberation
        # =========================================================================
        response: OfferResponse = await run_offer(
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

        if settings.USE_OFFER_DELIBERATION and response.deliberation:
            delib = response.deliberation

            # Log deliberation
            logger.info(
                "🎯 [SESSION %s] Deliberation: confidence=%.2f, flags=%s",
                session_id,
                delib.confidence,
                delib.flags or "none",
            )
            logger.debug(
                "📊 Views: customer='%s...', business='%s...', quality='%s...'",
                (delib.customer_view or "-")[:40],
                (delib.business_view or "-")[:40],
                (delib.quality_view or "-")[:40],
            )

            # CHECK: Price mismatch → CRITICAL, use fallback
            if "price_mismatch" in delib.flags:
                use_fallback = True
                fallback_reason = "price_mismatch"
                logger.error(
                    "🚨 [SESSION %s] PRICE MISMATCH → fallback activated!",
                    session_id,
                )
                track_metric("deliberation_price_mismatch", 1)

            # CHECK: Low confidence → use fallback
            elif delib.confidence < settings.DELIBERATION_MIN_CONFIDENCE:
                use_fallback = True
                fallback_reason = f"low_confidence_{delib.confidence:.2f}"
                logger.warning(
                    "⚠️ [SESSION %s] LOW CONFIDENCE %.2f < %.2f → fallback",
                    session_id,
                    delib.confidence,
                    settings.DELIBERATION_MIN_CONFIDENCE,
                )
                track_metric("deliberation_low_confidence", 1)

            # CHECK: Size unavailable (warning only, no fallback)
            if "size_unavailable" in delib.flags:
                logger.warning(
                    "⚠️ [SESSION %s] SIZE UNAVAILABLE flag (no fallback)",
                    session_id,
                )

        # =========================================================================
        # STEP 4: BUILD RESPONSE (normal or fallback)
        # =========================================================================
        if use_fallback:
            # Use safe fallback message instead of LLM response
            fallback_text = _get_fallback_text(fallback_reason)

            assistant_messages = [{"role": "assistant", "content": fallback_text}]

            # Stay in SIZE_COLOR to re-try with correct data
            return {
                "current_state": State.STATE_3_SIZE_COLOR.value,  # Go back!
                "messages": assistant_messages,
                "selected_products": validated_products,  # Keep validated
                "dialog_phase": "WAITING_FOR_SIZE",  # Re-ask
                "metadata": {"fallback_reason": fallback_reason},
                "step_number": state.get("step_number", 0) + 1,
                "last_error": None,
            }

        # Normal flow: use LLM response
        assistant_messages = [
            {"role": "assistant", "content": m.content} for m in response.messages
        ]
        if not assistant_messages:
            assistant_messages = [{"role": "assistant", "content": ""}]

        # Update selected_products if agent returned new products (preserve size/color/price).
        if response.products:
            incoming_products = [p.model_dump() for p in response.products]
            validated_products = _merge_products(validated_products, incoming_products)

        # =====================================================
        # DIALOG PHASE (Turn-Based State Machine)
        # =====================================================
        if settings.DEBUG_TRACE_LOGS:
            preview_text = assistant_messages[0].get("content", "") if assistant_messages else ""
            debug_log.node_exit(
                session_id=session_id,
                node_name="offer",
                goto="memory_update",
                new_phase="OFFER_MADE",
                response_preview=preview_text,
            )
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
