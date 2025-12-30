# helpers/payment/checkout.py
"""
Checkout flow - Initial payment preparation and HITL interrupt.
Extracted from payment.py for modularity.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from langgraph.types import Command, interrupt

from src.agents.pydantic.deps import create_deps_from_state
from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service
from src.services.observability import track_metric
from src.agents.langgraph.nodes.helpers.vision.snippet_loader import get_snippet_by_header

from .utils import ensure_prices_from_catalog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


async def prepare_payment_and_interrupt(
    state: dict[str, Any],
    runner: Callable[..., Any] | None,  # IGNORED - uses run_payment directly
    session_id: str,
) -> Command[Literal["payment", "end"]]:
    """Prepare payment details and trigger human approval interrupt."""
    start_time = time.perf_counter()

    # Get products for payment
    products = state.get("selected_products", []) or state.get("offered_products", [])
    products = await ensure_prices_from_catalog(products, session_id=session_id)
    total_price = sum(p.get("price", 0) for p in products)
    product_names = [p.get("name", "Товар") for p in products]

    # Get user message (handles both dict and LangChain Message objects)
    from src.agents.langgraph.nodes.utils import extract_user_message

    user_message = extract_user_message(state.get("messages", []))
    if not user_message:
        user_message = "Хочу оформити замовлення"

    # Create deps with payment context
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
    deps.selected_products = products
    try:
        from src.agents.langgraph.state_prompts import get_payment_sub_phase

        deps.payment_sub_phase = get_payment_sub_phase(state)
    except Exception:
        deps.payment_sub_phase = deps.payment_sub_phase

    # Custom strict template for checkout start (loaded from snippets.md)
    snippets = get_snippet_by_header("Підтвердження замовлення")
    if snippets:
         response_text = "\n\n".join(snippets)
    else:
         # Safety fallback
         response_text = (
            "Щоб одразу зарезервувати для вас замовлення, напишіть, будь ласка:\n\n"
            "📍Місто та відділення Нової Пошти\n"
            "📍ПІБ та номер телефону\n\n"
            "Як вам зручніше оплатити — повна оплата на рахунок ФОП (без додаткових комісій) "
            "чи передплата 200 грн, а решту при отриманні "
            "(але тоді Нова Пошта додатково нараховує комісію за післяплату)? 🤍"
         )

    latency_ms = (time.perf_counter() - start_time) * 1000
    track_metric("payment_prepare_latency_ms", latency_ms)

    # =========================================================================
    # CRITICAL: INTERRUPT FOR HUMAN APPROVAL
    # =========================================================================
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

    # =========================================================================
    # SITNIKS: Set status to "Виставлено рахунок" when showing payment details
    # =========================================================================
    if settings.ENABLE_CRM_INTEGRATION:
        try:
            sitniks_service = get_sitniks_chat_service()
            if sitniks_service.enabled:
                await sitniks_service.handle_invoice_sent(session_id)
                logger.info("[SESSION %s] Sitniks invoice_sent status set", session_id)
        except Exception as e:
            logger.warning("[SESSION %s] Sitniks invoice_sent error: %s", session_id, e)

    # =========================================================================
    # HITL CHECK: Skip interrupt for Telegram polling (lightweight mode)
    # =========================================================================
    if not settings.ENABLE_PAYMENT_HITL:
        from src.agents.langgraph.state_prompts import get_payment_sub_phase
        from src.agents.langgraph.nodes.helpers.policy_snippets import _reset_policy_counters

        payment_sub_phase = get_payment_sub_phase(state)

        # Map payment_sub_phase to dialog_phase deterministically
        phase_map = {
            "REQUEST_DATA": "WAITING_FOR_DELIVERY_DATA",
            "CONFIRM_DATA": "WAITING_FOR_PAYMENT_METHOD",
            "SHOW_PAYMENT": "WAITING_FOR_PAYMENT_PROOF",
            "THANK_YOU": "COMPLETED",
        }
        correct_dialog_phase = phase_map.get(payment_sub_phase, "WAITING_FOR_DELIVERY_DATA")

        # Reset policy counters if dialog phase changed
        old_dialog_phase = state.get("dialog_phase", "")
        if old_dialog_phase != correct_dialog_phase:
            metadata = state.get("metadata", {}).copy()
            metadata = _reset_policy_counters(metadata)
            logger.debug(
                "[SESSION %s] Payment dialog phase changed: %s -> %s, resetting policy counters",
                session_id,
                old_dialog_phase,
                correct_dialog_phase,
            )
            state["metadata"] = metadata

        logger.info(
            "[SESSION %s] HITL disabled - payment_sub_phase=%s -> dialog_phase=%s",
            session_id,
            payment_sub_phase,
            correct_dialog_phase,
        )

        # Split response into message bubbles
        response_parts = [p.strip() for p in response_text.split("\n\n") if p.strip()]
        assistant_messages = [{
            "role": "assistant", 
            "content": part
        } for part in response_parts] if response_parts else [{
            "role": "assistant", 
            "content": response_text
        }]

        cmd = Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": assistant_messages,
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{
                        "type": "text", 
                        "content": part
                    } for part in response_parts] if response_parts else [{
                        "type": "text", 
                        "content": response_text
                    }],
                    "metadata": {
                        "session_id": session_id,
                        "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                        "intent": "PAYMENT_DELIVERY",
                        "escalation_level": "NONE",
                    },
                },
                "dialog_phase": correct_dialog_phase,
                "awaiting_human_approval": False,
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",
        )

        if settings.DEBUG_TRACE_LOGS:
            debug_log.node_exit(
                session_id=session_id,
                node_name="payment",
                goto=cmd.goto,
                new_phase=correct_dialog_phase,
                response_preview=response_text,
            )
        return cmd

    # This call PAUSES the graph execution (HITL enabled)
    human_response = interrupt(approval_request)

    # When we get here, human has responded
    response_parts = [p.strip() for p in response_text.split("\n\n") if p.strip()]
    assistant_messages = [{
        "role": "assistant", 
        "content": part
    } for part in response_parts] if response_parts else [{
        "role": "assistant", 
        "content": response_text
    }]

    cmd = Command(
        update={
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "messages": assistant_messages,
            "agent_response": {
                "event": "simple_answer",
                "messages": [{
                    "type": "text", 
                    "content": part
                } for part in response_parts] if response_parts else [{
                    "type": "text", 
                    "content": response_text
                }],
                "metadata": {
                    "session_id": session_id,
                    "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                    "intent": "PAYMENT_DELIVERY",
                    "escalation_level": "NONE",
                },
            },
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
            "awaiting_human_approval": True,
            "approval_type": "payment",
            "approval_data": approval_request,
            "human_approved": human_response,
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="payment",
    )

    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_exit(
            session_id=session_id,
            node_name="payment",
            goto=cmd.goto,
            new_phase="WAITING_FOR_PAYMENT_PROOF",
            response_preview=response_text,
        )
    return cmd
