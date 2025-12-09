"""
Payment Node - Human-in-the-loop for money.
============================================
CRITICAL NODE. This is where money changes hands.
MUST have human approval before processing.

QUALITY IMPLEMENTATION:
- Sub-phases: REQUEST_DATA → CONFIRM_DATA → SHOW_PAYMENT → THANK_YOU
- Детальні промпти для кожного кроку
- Правильна логіка переходів
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from langgraph.types import Command, interrupt

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.payment_agent import run_payment
from src.core.state_machine import State
from src.services.observability import log_agent_step, track_metric

# State prompts for sub-phases
from ..state_prompts import get_payment_sub_phase, get_state_prompt


if TYPE_CHECKING:
    from collections.abc import Callable


logger = logging.getLogger(__name__)


# =============================================================================
# PAYMENT SUB-PHASE TEMPLATES (from n8n prompt)
# =============================================================================

PAYMENT_TEMPLATES = {
    "REQUEST_DATA": """Щоб одразу зарезервувати для вас замовлення, напишіть, будь ласка:
📍Місто та відділення Нової пошти
📍ПІБ та номер телефону

Як вам зручніше оплатити - повна оплата на рахунок ФОП (без додаткових комісій) чи передплата 200 грн, а решту при отриманні (але тоді Нова пошта додатково нараховує комісію за післяплату) 🤍""",

    "CONFIRM_DATA": "Підтверджую дані замовлення: {product_name} - {color} - розмір {size} - {price} грн. Отримувач: {name}, телефон {phone}, місто {city}, НП {nova_poshta}. Перевірте, будь ласка, чи все вірно.",

    "SHOW_PAYMENT": """Сума до сплати зараз: {amount} грн.

Отримувач: ФОП Кутний Михайло Михайлович
IBAN: UA653220010000026003340139893
ІПН/ЄДРПОУ: 3278315599
Призначення платежу: ОПЛАТА ЗА ТОВАР

Надішліть, будь ласка, скрін квитанції після оплати, щоб ми одразу сформували ваше замовлення 🤍""",

    "THANK_YOU": """Дякуємо за замовлення🥰

Гарного вам дня та мирного неба 🕊""",
}


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
        return await _handle_approval_response(state, session_id)

    # First entry - prepare payment and request approval
    return await _prepare_payment_and_interrupt(state, runner, session_id)


async def _prepare_payment_and_interrupt(
    state: dict[str, Any],
    runner: Callable[..., Any] | None,  # IGNORED - uses run_payment directly
    session_id: str,
) -> Command[Literal["payment"]]:
    """Prepare payment details and trigger human approval interrupt."""
    start_time = time.perf_counter()

    # Get products for payment
    products = state.get("selected_products", []) or state.get("offered_products", [])
    total_price = sum(p.get("price", 0) for p in products)
    product_names = [p.get("name", "Товар") for p in products]

    # Get user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message

    user_message = extract_user_message(state.get("messages", []))
    if not user_message:
        user_message = "Хочу оформити замовлення"

    # Create deps with payment context
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
    deps.selected_products = products

    try:
        # Call payment agent DIRECTLY
        response = await run_payment(
            message=user_message,
            deps=deps,
            message_history=None,
        )
        response_text = response.reply_to_user
    except Exception as e:
        logger.error("Payment LLM call failed: %s", e)
        # Fallback response
        response_text = (
            "Чудово! Для оформлення замовлення надішліть:\n"
            "📝 ПІБ\n"
            "📱 Телефон\n"
            "🏙️ Місто та відділення Нової Пошти\n\n"
            f"Сума до сплати: {total_price} грн"
        )

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
    #
    # DIALOG PHASE: WAITING_FOR_PAYMENT_PROOF
    # - Показали реквізити, чекаємо скрін оплати
    return Command(
        update={
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "messages": [{"role": "assistant", "content": response_text}],
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
            "awaiting_human_approval": True,
            "approval_type": "payment",
            "approval_data": approval_request,
            "human_approved": human_response,  # True/False from human
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="payment",  # Loop back to process approval
    )


async def _handle_approval_response(
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

        # =========================================================================
        # SAVE ORDER TO DB (Persistence)
        # =========================================================================
        crm_order_result = None
        try:
            deps = create_deps_from_state(state)

            # Construct order payload
            products = state.get("selected_products", [])
            order_items = []
            for p in products:
                order_items.append(
                    {
                        "product_id": p.get("id"),
                        "name": p.get("name"),
                        "price": p.get("price"),
                        "size": p.get("size"),
                        "color": p.get("color"),
                        "quantity": 1,
                    }
                )

            order_data = {
                "external_id": session_id,
                "source_id": deps.user_id,
                "customer": {
                    "full_name": deps.customer_name,
                    "phone": deps.customer_phone,
                    "city": deps.customer_city,
                    "nova_poshta_branch": deps.customer_nova_poshta,
                    "telegram_id": session_id if "telegram" in str(deps.user_id) else None,
                    "manychat_id": session_id if "manychat" in str(deps.user_id) else None,
                },
                "items": order_items,
                "totals": {"total": approval_data.get("total_price", 0)},
                "status": "new",
                "delivery_method": "nova_poshta",
                "notes": "Created via Mirt-AI Agent",
                "source": "telegram" if "telegram" in str(deps.user_id) else "manychat",
            }

            order_id = await deps.db.create_order(order_data)
            if order_id:
                logger.info("Order successfully saved to Supabase: ID %s", order_id)
            else:
                logger.error("Failed to save order to Supabase (returned None)")

            # =========================================================================
            # CREATE ORDER IN SNITKIX CRM (Async via Celery)
            # =========================================================================
            from src.integrations.crm.crmservice import get_crm_service

            crm_service = get_crm_service()
            crm_order_result = await crm_service.create_order_with_persistence(
                session_id=session_id,
                order_data=order_data,
                external_id=f"{session_id}_{int(time.time())}",  # Unique external ID
            )

            logger.info(
                "CRM order creation result for session %s: %s",
                session_id,
                crm_order_result.get("status", "unknown"),
            )

        except Exception as e:
            logger.exception("CRITICAL: Failed to save order to DB or queue CRM: %s", e)
            crm_order_result = {"status": "failed", "error": str(e)}

        # DIALOG PHASE: UPSELL_OFFERED (STATE_6)
        # - Оплата підтверджена, пропонуємо допродаж
        if crm_order_result and crm_order_result.get("status") in ["failed", "error"]:
            # CRM creation failed - route to error handler
            return Command(
                update={
                    "awaiting_human_approval": False,
                    "approval_type": None,
                    "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                    "dialog_phase": "CRM_ERROR_HANDLING",
                    "crm_order_result": crm_order_result,
                    "crm_external_id": crm_order_result.get("external_id"),
                    "crm_retry_count": 0,
                    "step_number": state.get("step_number", 0) + 1,
                },
                goto="crm_error",
            )
        else:
            # CRM creation queued/successful - proceed to upsell
            return Command(
                update={
                    "awaiting_human_approval": False,
                    "approval_type": None,
                    "current_state": State.STATE_6_UPSELL.value,
                    "dialog_phase": "UPSELL_OFFERED",
                    "crm_order_result": crm_order_result,
                    "crm_external_id": crm_order_result.get("external_id") if crm_order_result else None,
                    "step_number": state.get("step_number", 0) + 1,
                },
                goto="upsell",
            )
    else:
        # Payment rejected - back to offer
        logger.info("Payment REJECTED for session %s", session_id)
        track_metric("payment_rejected", 1, {"session_id": session_id})

        # DIALOG PHASE: OFFER_MADE (повертаємо до STATE_4)
        # - Юзер може спробувати ще раз
        return Command(
            update={
                "awaiting_human_approval": False,
                "approval_type": None,
                "human_approved": None,
                "current_state": State.STATE_4_OFFER.value,
                "dialog_phase": "OFFER_MADE",
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",
        )
