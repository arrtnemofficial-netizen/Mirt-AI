"""
Offer Node - Product presentation with Multi-Role Deliberation.
================================================================
Presents product offer with price and details.
This is where we close the sale.

DELIBERATION FLOW:
1. Pre-validation: Check prices against DB before LLM call
2. LLM generates offer with deliberation (Customer/Business/Quality views)
3. Post-validation: If low confidence or price_mismatch → fallback
4. Return offer to customer

Uses run_support directly with offer context.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.support_agent import run_support
from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.services.catalog_service import CatalogService
from src.services.observability import log_agent_step, track_metric


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents.pydantic.models import SupportResponse


logger = logging.getLogger(__name__)


# =============================================================================
# FALLBACK MESSAGES (коли deliberation failed)
# =============================================================================
FALLBACK_PRICE_MISMATCH = (
    "Секундочку, уточнюю ціну по каталогу 🤍\n---\nЗараз напишу точну інформацію"
)

FALLBACK_LOW_CONFIDENCE = (
    "Дайте подивлюсь ще раз по каталогу 🌸\n---\nХочу переконатися що все точно"
)


async def offer_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,  # Kept for signature compatibility
) -> dict[str, Any]:
    """
    Present product offer with price and details.

    DELIBERATION FLOW (if USE_OFFER_DELIBERATION=True):
    1. PRE-VALIDATION: Verify prices against DB before LLM call
    2. LLM CALL: Generate offer with deliberation views
    3. POST-VALIDATION: Check confidence and flags
    4. FALLBACK: If price_mismatch or low confidence → safe message

    Args:
        state: Current conversation state
        runner: IGNORED - uses run_support directly

    Returns:
        State update with offer response
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    trace_id = state.get("trace_id", "")

    # Get user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message

    user_message = extract_user_message(state.get("messages", []))

    if not user_message:
        user_message = "Покажи товар"

    # Get products to offer
    selected_products = state.get("selected_products", [])

    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_entry(
            session_id=session_id,
            node_name="offer",
            phase=state.get("dialog_phase", "?"),
            state_name=State.STATE_4_OFFER.value,
            extra={
                "products": str(len(selected_products)),
                "msg": user_message,
            },
        )

    # =========================================================================
    # STEP 1: PRE-VALIDATION (перевірка цін по БД ДО LLM виклику)
    # =========================================================================
    validated_products = selected_products.copy()
    price_validation_passed = True

    if settings.USE_OFFER_DELIBERATION and selected_products:
        validated_products, price_validation_passed = await _validate_prices_from_db(
            selected_products, session_id
        )

    # Create deps with offer context + validated prices
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_4_OFFER.value
    deps.selected_products = validated_products  # Use validated prices!

    logger.info(
        "🎁 [SESSION %s] Offer node: products=%d, price_validation=%s",
        session_id,
        len(selected_products),
        "PASS" if price_validation_passed else "CORRECTED",
    )

    try:
        # =========================================================================
        # STEP 2: LLM CALL with deliberation
        # =========================================================================
        response: SupportResponse = await run_support(
            message=user_message,
            deps=deps,
            message_history=None,
        )

        # Store offered products for tracking
        offered_products = validated_products.copy()
        latency_ms = (time.perf_counter() - start_time) * 1000

        log_agent_step(
            session_id=session_id,
            state=State.STATE_4_OFFER.value,
            intent=response.metadata.intent,
            event=response.event,
            latency_ms=latency_ms,
            extra={"trace_id": trace_id, "offered_products": len(offered_products)},
        )
        track_metric("offer_node_latency_ms", latency_ms)

        # =========================================================================
        # STEP 3: POST-VALIDATION (deliberation check)
        # =========================================================================
        use_fallback = False
        fallback_reason = ""

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
            if fallback_reason.startswith("price"):
                fallback_text = FALLBACK_PRICE_MISMATCH
            else:
                fallback_text = FALLBACK_LOW_CONFIDENCE

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

        # Update selected_products if agent returned new products
        if response.products:
            validated_products = [p.model_dump() for p in response.products]

        # =====================================================
        # DIALOG PHASE (Turn-Based State Machine)
        # CRITICAL: Phase must match actual UX - if response asks for delivery data,
        # phase must be WAITING_FOR_DELIVERY_DATA, not OFFER_MADE
        # =====================================================
        # Determine phase based on response content and intent
        dialog_phase = "OFFER_MADE"  # Default
        
        # Check if response asks for delivery data (місто, відділення, ПІБ, телефон)
        # SAFETY: Convert None to empty string to prevent TypeError in join()
        response_text = " ".join([str(m.get("content", "") or "") for m in assistant_messages]).lower()
        delivery_keywords = [
            "місто", "відділення", "нової пошти", "нова пошта", "піб", "прізвище",
            "телефон", "номер телефону", "надішліть", "напишіть", "вкажіть",
            "бронюємо", "зарезервувати", "оформити", "замовлення"
        ]
        asks_for_delivery = any(keyword in response_text for keyword in delivery_keywords)
        
        # Check intent from LLM response
        response_intent = response.metadata.intent if hasattr(response.metadata, "intent") else ""
        user_confirmed = response_intent == "PAYMENT_DELIVERY" or asks_for_delivery
        
        # If LLM asks for delivery data OR intent is PAYMENT_DELIVERY → transition to payment phase
        # NOTE: user_confirmed already includes asks_for_delivery, so no need to check both
        if user_confirmed:
            dialog_phase = "WAITING_FOR_DELIVERY_DATA"
            logger.info(
                "🔄 [SESSION %s] Offer → Payment transition: intent=%s, asks_delivery=%s → phase=%s",
                session_id,
                response_intent,
                asks_for_delivery,
                dialog_phase,
            )
        
        if settings.DEBUG_TRACE_LOGS:
            preview_text = assistant_messages[0].get("content", "") if assistant_messages else ""
            debug_log.node_exit(
                session_id=session_id,
                node_name="offer",
                goto="memory_update",
                new_phase=dialog_phase,
                response_preview=preview_text,
            )
        
        # If transitioning to payment, also update state
        new_state = State.STATE_4_OFFER.value
        if dialog_phase == "WAITING_FOR_DELIVERY_DATA":
            new_state = State.STATE_5_PAYMENT_DELIVERY.value
            logger.info(
                "🔄 [SESSION %s] Offer node: state transition %s → %s (phase=%s)",
                session_id,
                State.STATE_4_OFFER.value,
                new_state,
                dialog_phase,
            )
        
        return {
            "current_state": new_state,
            "messages": assistant_messages,
            "metadata": response.metadata.model_dump(),
            "selected_products": validated_products,
            "offered_products": offered_products,
            "agent_response": response.model_dump(),
            "dialog_phase": dialog_phase,
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
        }

    except Exception as e:
        logger.exception("Offer node failed for session %s: %s", session_id, e)

        if settings.DEBUG_TRACE_LOGS:
            debug_log.error(
                session_id=session_id,
                error_type=type(e).__name__,
                message=str(e) or type(e).__name__,
            )

        return {
            "last_error": str(e),
            "tool_errors": [*state.get("tool_errors", []), f"Offer error: {e}"],
            "retry_count": state.get("retry_count", 0) + 1,
            "step_number": state.get("step_number", 0) + 1,
        }


# =============================================================================
# PRE-VALIDATION HELPER
# =============================================================================


async def _validate_prices_from_db(
    products: list[dict[str, Any]], session_id: str
) -> tuple[list[dict[str, Any]], bool]:
    """
    Validate and correct product prices from database.

    Returns:
        (validated_products, all_prices_correct)
        - validated_products: products with corrected prices from DB
        - all_prices_correct: True if no corrections were needed
    """
    catalog = CatalogService()
    validated = []
    all_correct = True

    for product in products:
        product_name = product.get("name", "")
        claimed_price = product.get("price", 0)
        size = product.get("size")

        # Lookup in DB
        try:
            results = await catalog.search_products(query=product_name, limit=1)
            if results:
                db_product = results[0]
                db_price = CatalogService.get_price_for_size(db_product, size)

                # Always ensure a usable price is present.
                # This is critical when the DB schema relies on price_by_size and may not have products.price.
                if not claimed_price or claimed_price <= 0:
                    all_correct = False
                    product = {**product, "price": db_price}
                    logger.info(
                        "💰 [SESSION %s] Filled missing price for '%s' (size=%s): DB=%s",
                        session_id,
                        product_name,
                        size,
                        db_price,
                    )
                # Check if prices match (allow 5% tolerance for rounding)
                elif abs(db_price - claimed_price) > claimed_price * 0.05:
                    logger.warning(
                        "💰 [SESSION %s] Price mismatch for '%s': claimed=%s, DB=%s → CORRECTING",
                        session_id,
                        product_name,
                        claimed_price,
                        db_price,
                    )
                    all_correct = False
                    product = {**product, "price": db_price}  # Correct price!
                else:
                    logger.debug(
                        "✅ Price verified for '%s': %s грн",
                        product_name,
                        db_price,
                    )
        except Exception as e:
            logger.warning("DB lookup failed for '%s': %s", product_name, e)

        validated.append(product)

    return validated, all_correct


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
