"""
Payment Node - Human-in-the-loop for money.
============================================
CRITICAL NODE. This is where money changes hands.
MUST have human approval before processing.

This is NOT optional. This is insurance against:
- Hallucinated discounts
- Fraudulent refunds
- Accidental charges
- Compliance violations
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Literal

from langgraph.types import Command, interrupt  # noqa: F401

from src.core.models import AgentResponse, Message, Metadata
from src.core.state_machine import State
from src.services.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


async def payment_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> Command[Literal["upsell", "end", "payment", "validation"]]:
    """
    Handle payment with MANDATORY human approval.

    This node uses LangGraph's interrupt() for human-in-the-loop.
    The graph STOPS here and waits for explicit approval.

    Flow:
    1. First entry: Generate payment details, trigger interrupt
    2. Resume with approval: Process to upsell
    3. Resume with rejection: Return to offer or end

    Args:
        state: Current conversation state
        runner: LLM runner function

    Returns:
        Command for next node based on approval
    """
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # Check if we're resuming from interrupt
    if state.get("awaiting_human_approval"):
        return _handle_approval_response(state, session_id)

    # First entry - prepare payment and request approval
    return await _prepare_payment_and_interrupt(state, runner, session_id)


async def _prepare_payment_and_interrupt(
    state: dict[str, Any],
    runner: Callable[..., Any] | None,
    session_id: str,
) -> Command[Literal["payment"]]:
    """Prepare payment details and trigger human approval interrupt."""
    start_time = time.perf_counter()

    # Get products for payment
    products = state.get("selected_products", []) or state.get("offered_products", [])
    total_price = sum(p.get("price", 0) for p in products)
    product_names = [p.get("name", "Товар") for p in products]

    # Generate payment message via LLM
    prepared_metadata = {
        **state.get("metadata", {}),
        "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
        "system_instructions": (
            "Клієнт готовий до оплати! "
            "1. Надай реквізити для оплати (ФОП Крупка, ПриватБанк) "
            "2. Вкажи суму до сплати "
            "3. Попроси дані для доставки: ПІБ, телефон, місто, відділення НП "
            "4. Будь ввічливою та підтримуючою"
        ),
    }

    try:
        response = await runner(state.get("messages", []), prepared_metadata)
        response_json = response.model_dump_json()
    except Exception as e:
        logger.error("Payment LLM call failed: %s", e)
        # Fallback response
        response_json = AgentResponse(
            event="checkout",
            messages=[Message(content=(
                "Чудово! Для оформлення замовлення надішліть:\n"
                "📝 ПІБ\n"
                "📱 Телефон\n"
                "🏙️ Місто та відділення Нової Пошти\n\n"
                f"Сума до сплати: {total_price} грн"
            ))],
            products=[],
            metadata=Metadata(
                session_id=session_id,
                current_state=State.STATE_5_PAYMENT_DELIVERY.value,
                intent="PAYMENT_DELIVERY",
            ),
        ).model_dump_json()

    latency_ms = (time.perf_counter() - start_time) * 1000
    track_metric("payment_prepare_latency_ms", latency_ms)

    # =========================================================================
    # CRITICAL: INTERRUPT FOR HUMAN APPROVAL
    # =========================================================================
    # The graph STOPS here. Nothing moves forward without human saying "OK".
    # This is your insurance policy.

    approval_request = {
        "type": "payment_confirmation",
        "session_id": session_id,
        "total_price": total_price,
        "products": product_names,
        "message": "Підтвердіть оплату для цього замовлення",
        "requires_action": True,
        "timestamp": time.time(),
    }

    logger.info(
        "Payment interrupt triggered for session %s: %s грн, products: %s",
        session_id,
        total_price,
        product_names,
    )

    # This call PAUSES the graph execution
    # It returns ONLY when someone calls graph.invoke(Command(resume=...))
    human_response = interrupt(approval_request)

    # When we get here, human has responded
    # Update state and loop back to process the response
    return Command(
        update={
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "messages": [{"role": "assistant", "content": response_json}],
            "awaiting_human_approval": True,
            "approval_type": "payment",
            "approval_data": approval_request,
            "human_approved": human_response,  # True/False from human
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="payment",  # Loop back to process approval
    )


def _handle_approval_response(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["upsell", "end", "validation"]]:
    """Handle the human's approval response."""

    approved = state.get("human_approved")
    approval_data = state.get("approval_data", {})

    log_agent_step(
        session_id=session_id,
        state=State.STATE_5_PAYMENT_DELIVERY.value,
        intent="PAYMENT_DELIVERY",
        event="payment_approval",
        extra={
            "approved": approved,
            "total_price": approval_data.get("total_price"),
        },
    )

    if approved:
        # Payment approved - proceed to upsell
        logger.info("Payment APPROVED for session %s", session_id)
        track_metric("payment_approved", 1, {"session_id": session_id})

        return Command(
            update={
                "awaiting_human_approval": False,
                "approval_type": None,
                "current_state": State.STATE_6_UPSELL.value,
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="upsell",
        )
    else:
        # Payment rejected - back to validation or end
        logger.info("Payment REJECTED for session %s", session_id)
        track_metric("payment_rejected", 1, {"session_id": session_id})

        return Command(
            update={
                "awaiting_human_approval": False,
                "approval_type": None,
                "human_approved": None,
                "current_state": State.STATE_4_OFFER.value,
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",
        )
