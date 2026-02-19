# helpers/payment/method_selection.py
"""
Payment method selection - Handle user's payment method choice.
Extracted from payment.py for modularity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from langgraph.types import Command

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.payment_agent import run_payment
from src.conf.config import settings
from src.core.fallbacks import get_payment_fallback_text
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.services.observability import track_metric

from .utils import ensure_prices_from_catalog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


async def handle_payment_method_selection(
    state: dict[str, Any],
    runner: Callable[..., Any] | None,
    session_id: str,
) -> Command[Literal["end", "payment"]]:
    """
    Handle payment method selection (full payment vs prepayment).
    
    User has chosen payment method ("Повна оплата" / "Передплата").
    We show requisites and transition to WAITING_FOR_PAYMENT_PROOF.
    """
    from src.agents.langgraph.nodes.utils import extract_user_message

    user_message = extract_user_message(state.get("messages", []))
    products = state.get("selected_products", []) or state.get("offered_products", [])
    products = await ensure_prices_from_catalog(products, session_id=session_id)
    total_price = sum(p.get("price", 0) for p in products)

    # Create deps with payment context
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
    deps.selected_products = products

    # Set sub-phase to SHOW_PAYMENT (we're about to show requisites)
    deps.payment_sub_phase = "SHOW_PAYMENT"

    try:
        # Call payment agent to generate response with requisites
        response = await run_payment(
            message=user_message,
            deps=deps,
            message_history=None,
        )
        response_text = response.reply_to_user or ""

        # Mark that payment details were sent
        metadata_update = state.get("metadata", {}).copy()
        metadata_update["payment_details_sent"] = True
        metadata_update["awaiting_payment_confirmation"] = True

    except Exception as e:
        logger.error("[SESSION %s] Payment method selection processing error: %s", session_id, e)
        if settings.STRICT_EXCEPTION_POLICY:
            try:
                track_metric(
                    "fallback_triggered",
                    1,
                    {
                        "fallback_reason": type(e).__name__,
                        "session_id": session_id,
                        "state": State.STATE_5_PAYMENT_DELIVERY.value,
                        "node": "payment_method_selection",
                    },
                )
            except Exception as metric_error:
                logger.debug(
                    "[SESSION %s] Failed to emit payment method fallback metric: %s",
                    session_id,
                    metric_error,
                )
        # Fallback: show requisites directly
        try:
            from src.conf.payment_config import format_requisites_with_receipt_request

            requisites_parts = format_requisites_with_receipt_request(price=int(total_price))
            response_text = "\n\n".join(requisites_parts)
        except Exception as fallback_error:
            logger.error(
                "[SESSION %s] Requisites fallback formatting failed: %s",
                session_id,
                fallback_error,
            )
            response_text = get_payment_fallback_text()
        metadata_update = state.get("metadata", {}).copy()
        metadata_update["payment_details_sent"] = True
        metadata_update["awaiting_payment_confirmation"] = True

    logger.info(
        "[SESSION %s] Payment method selected: '%s', showing requisites",
        session_id,
        user_message[:50] if user_message else "(empty)",
    )

    # Split response into message bubbles
    response_parts = [p.strip() for p in response_text.split("\n\n") if p.strip()]
    if not response_parts:
        response_parts = [response_text]
    assistant_messages = [{"role": "assistant", "content": part} for part in response_parts]

    cmd = Command(
        update={
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "messages": assistant_messages,
            "agent_response": {
                "event": "simple_answer",
                "messages": [{"type": "text", "content": part} for part in response_parts],
                "metadata": {
                    "session_id": session_id,
                    "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                    "intent": "PAYMENT_DELIVERY",
                    "escalation_level": "NONE",
                },
            },
            "metadata": metadata_update,
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",  # Now waiting for screenshot
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="end",
    )

    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_exit(
            session_id=session_id,
            node_name="payment",
            goto=cmd.goto,
            new_phase="WAITING_FOR_PAYMENT_PROOF",
            response_preview=response_text[:100],
        )
    return cmd
