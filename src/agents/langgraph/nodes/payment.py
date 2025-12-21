"""
Payment Node - Human-in-the-loop for money.
============================================
<<<<<<< Updated upstream
CRITICAL NODE. This is where money changes hands.
MUST have human approval before processing.

This is NOT optional. This is insurance against:
- Hallucinated discounts
- Fraudulent refunds
- Accidental charges
- Compliance violations
=======
Refactored to be a thin orchestrator.
Logic moved to src.services.payment_*
>>>>>>> Stashed changes
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from langgraph.types import Command, interrupt

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.payment_agent import run_payment
from src.core.state_machine import State
<<<<<<< Updated upstream
from src.services.observability import log_agent_step, track_metric

=======
from src.services.core.observability import track_metric
from src.core.prompt_registry import get_snippet_by_header

from src.services.domain.payment.payment_validation import (
    validate_phone_number,
    detect_payment_proof,
    get_payment_sub_phase,
    is_order_ready
)
from src.services.domain.payment.payment_crm import hydrate_prices, create_and_submit_order
from src.services.domain.payment.payment_notifications import notify_order_success, notify_payment_critical_error
>>>>>>> Stashed changes

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


<<<<<<< Updated upstream
=======
def _get_snippet_text(header: str, default: str) -> str:
    """Helper to get snippet text from registry."""
    bubbles = get_snippet_by_header(header)
    return "\n---\n".join(bubbles) if bubbles else default


PAYMENT_TEMPLATES = {
    "THANK_YOU": _get_snippet_text("Дякуємо за замовлення", "Дякуємо за замовлення🥰\n\nГарного вам дня та мирного неба 🕊"),
}


>>>>>>> Stashed changes
async def payment_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> Command[Literal["upsell", "end", "payment", "validation"]]:
    """
    Handle payment with MANDATORY human approval.

    This node uses LangGraph's interrupt() for human-in-the-loop.
    The graph STOPS here and waits for explicit approval.
    """
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # Check if we're resuming from interrupt
    if state.get("awaiting_human_approval"):
        return await _handle_approval_response(state, session_id)

<<<<<<< Updated upstream
=======
    # Check if we're in WAITING_FOR_PAYMENT_PROOF phase (HITL disabled mode)
    if dialog_phase == "WAITING_FOR_PAYMENT_PROOF":
        return await _handle_delivery_data(state, runner, session_id)

>>>>>>> Stashed changes
    # First entry - prepare payment and request approval
    return await _prepare_payment_and_interrupt(state, runner, session_id)


async def _prepare_payment_and_interrupt(
    state: dict[str, Any],
    runner: Callable[..., Any] | None,  # IGNORED
    session_id: str,
) -> Command[Literal["payment"]]:
    """Prepare payment details and trigger human approval interrupt."""
    start_time = time.perf_counter()

    labels_json = get_snippet_by_header("VISION_LABELS")
    labels = json.loads(labels_json[0]) if labels_json else {}
    
    products = state.get("selected_products", []) or state.get("offered_products", [])
<<<<<<< Updated upstream
=======
    products = await hydrate_prices(products, session_id=session_id)
>>>>>>> Stashed changes
    total_price = sum(p.get("price", 0) for p in products)
    product_names = [p.get("name", labels.get("default_product", "Товар")) for p in products]

    # Get user message
    from .utils import extract_user_message
<<<<<<< Updated upstream
    user_message = extract_user_message(state.get("messages", []))
    if not user_message:
        user_message = "Хочу оформити замовлення"
=======
    user_message = extract_user_message(state.get("messages", [])) or labels.get("default_action", "Оформлення")
>>>>>>> Stashed changes

    # Create deps with payment context
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
    deps.selected_products = products
<<<<<<< Updated upstream
=======
    
    metadata = state.get("metadata", {})
    deps.payment_sub_phase = get_payment_sub_phase(metadata)
>>>>>>> Stashed changes

    try:
        response = await run_payment(
            message=user_message,
            deps=deps,
            message_history=state.get("messages", [])
        )
        response_text = response.reply_to_user
    except Exception as e:
        logger.error("Payment LLM call failed: %s", e)
        response_text = _get_snippet_text("Очікуємо на дані (доставка)", "Вкажіть дані для доставки")
        price_tmpl = get_snippet_by_header("PAYMENT_TOTAL_PRICE_TEMPLATE")
        if price_tmpl:
             response_text += "\n\n" + price_tmpl[0].format(total=total_price, currency=labels.get("currency_uah", "грн"))
        else:
             response_text += f"\n\nСума до сплати: {total_price} {labels.get('currency_uah', 'грн')}"

    latency_ms = (time.perf_counter() - start_time) * 1000
    track_metric("payment_prepare_latency_ms", latency_ms)

    approval_request = {
        "type": "payment_confirmation",
        "session_id": session_id,
        "total_price": total_price,
        "products": product_names,
        "requires_action": True,
        "timestamp": time.time(),
    }

<<<<<<< Updated upstream
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
=======
    # HITL CHECK
    if not settings.ENABLE_PAYMENT_HITL:
        return Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": [{"role": "assistant", "content": response_text}],
                "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
                "awaiting_human_approval": False,
                "selected_products": products,
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",
        )

    human_response = interrupt(approval_request)

>>>>>>> Stashed changes
    return Command(
        update={
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "messages": [{"role": "assistant", "content": response_text}],
<<<<<<< Updated upstream
=======
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
>>>>>>> Stashed changes
            "awaiting_human_approval": True,
            "approval_type": "payment",
            "approval_data": approval_request,
            "human_approved": human_response,
            "selected_products": products,
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="payment",
    )

<<<<<<< Updated upstream
=======

async def _handle_delivery_data(
    state: dict[str, Any],
    runner: Callable[..., Any] | None,
    session_id: str,
) -> Command[Literal["upsell", "end", "agent"]]:
    """Handle delivery data and proof detection."""
    from .utils import extract_user_message
    user_message = extract_user_message(state.get("messages", []))
    
    metadata = state.get("metadata", {}).copy()
    products = state.get("selected_products", []) or state.get("offered_products", [])
    products = await hydrate_prices(products, session_id=session_id)
    
    has_image = bool(state.get("has_image") or metadata.get("has_image"))

    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
    deps.selected_products = products
    deps.payment_sub_phase = get_payment_sub_phase(metadata)

    try:
        response = await run_payment(user_message, deps)
        
        # Validation & Normalization
        if deps.customer_phone:
            valid = validate_phone_number(deps.customer_phone)
            if valid:
                metadata["customer_phone"] = valid
            else:
                fallback = get_snippet_by_header("PAYMENT_INVALID_PHONE_FALLBACK")
                labels_json = get_snippet_by_header("VISION_LABELS")
                labels = json.loads(labels_json[0]) if labels_json else {}
                response.reply_to_user = (fallback[0] if fallback else labels.get("invalid_phone", "Невалідний номер")) + "\n\n" + response.reply_to_user

        # Sync metadata
        for field in ["customer_name", "customer_city", "customer_nova_poshta"]:
            val = getattr(deps, field, None)
            if val: metadata[field] = val

        # Proof detection
        if detect_payment_proof(user_message, has_image):
            metadata["payment_proof_received"] = True

        ready, missing = is_order_ready(metadata)
        
        if ready and metadata.get("payment_proof_received"):
             # Flow completed
             return Command(
                 update={
                     "current_state": State.STATE_7_END.value,
                     "messages": [{"role": "assistant", "content": response.reply_to_user}],
                     "metadata": metadata,
                     "dialog_phase": "COMPLETED",
                     "should_escalate": True,
                     "escalation_reason": "ORDER_CONFIRMED",
                     "step_number": state.get("step_number", 0) + 1,
                 },
                 goto="end",
             )

        return Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": [{"role": "assistant", "content": response.reply_to_user}],
                "metadata": metadata,
                "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",
        )

    except Exception as e:
        logger.error("Delivery handling failed: %s", e)
        return Command(update={"dialog_phase": "ERROR"}, goto="end")

>>>>>>> Stashed changes

async def _handle_approval_response(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["upsell", "end", "validation"]]:
    """Process human approval and CRM submission."""
    approved = state.get("human_approved")
    approval_data = state.get("approval_data", {})
<<<<<<< Updated upstream

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
        try:
            deps = create_deps_from_state(state)
            
            # Construct order payload
            # Ensure products have necessary fields
            products = state.get("selected_products", [])
            order_items = []
            for p in products:
                order_items.append({
                    "product_id": p.get("id"), # Assuming ID is present
                    "name": p.get("name"),
                    "price": p.get("price"),
                    "size": p.get("size"), # Might be missing if not selected yet? 
                    # Actually at payment stage size MUST be selected.
                    "color": p.get("color"),
                    "quantity": 1
                })

            order_data = {
                "external_id": session_id,
                "source_id": deps.user_id,
                "customer": {
                    "name": deps.customer_name,
                    "phone": deps.customer_phone,
                    "city": deps.customer_city,
                    "delivery_address": deps.customer_nova_poshta,
                },
                "items": order_items,
                "totals": {
                    "total": approval_data.get("total_price", 0)
                },
                "status": "new",
                "delivery_method": "nova_poshta",
                "notes": "Created via Mirt-AI Agent"
            }

            order_id = await deps.db.create_order(order_data)
            if order_id:
                logger.info("Order successfully saved to Supabase: ID %s", order_id)
            else:
                logger.error("Failed to save order to Supabase (returned None)")

        except Exception as e:
            logger.exception("CRITICAL: Failed to save order to DB: %s", e)
            # We don't stop the flow, but we log critical error

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
=======
    metadata = state.get("metadata", {})
    
    if approved:
        total = approval_data.get("total_price", 0)
        res = await create_and_submit_order(
            session_id=session_id,
            user_id=state.get("user_id", ""),
            user_nickname=state.get("user_nickname"),
            metadata=metadata,
            products=state.get("selected_products", []),
            total_price=total
        )
        
        if res.get("status") == "failed":
            await notify_payment_critical_error(session_id, res.get("error", "Unknown"))
            return Command(update={"dialog_phase": "CRM_ERROR"}, goto="end")
            
        # Notify Success
        await notify_order_success(session_id, total, approval_data.get("products", []))
        
        return Command(
            update={
                "awaiting_human_approval": False,
                "current_state": State.STATE_6_UPSELL.value,
                "dialog_phase": "UPSELL_OFFERED",
>>>>>>> Stashed changes
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="upsell",
        )
    
    return Command(
        update={
            "awaiting_human_approval": False,
            "current_state": State.STATE_4_OFFER.value,
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="end",
    )
