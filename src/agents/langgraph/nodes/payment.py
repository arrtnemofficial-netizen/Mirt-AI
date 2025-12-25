"""
Payment Node - Human-in-the-loop for money.
============================================
Refactored to be a thin orchestrator.
Logic moved to src.services.payment_*
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from langgraph.types import Command, interrupt

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.payment_agent import run_payment
from src.conf.config import settings
from src.core.state_machine import State
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

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def _get_snippet_text(header: str, default: str) -> str:
    """Helper to get snippet text from registry."""
    bubbles = get_snippet_by_header(header)
    return "\n---\n".join(bubbles) if bubbles else default


PAYMENT_TEMPLATES = {
    "THANK_YOU": _get_snippet_text(
        "PAYMENT_THANK_YOU",
        "Thank you for your order.\n\nHave a great day.",
    ),
}


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
    dialog_phase = state.get("dialog_phase", "")

    # Check if we're resuming from interrupt
    if state.get("awaiting_human_approval"):
        return await _handle_approval_response(state, session_id)

    # Check if we're in WAITING_FOR_PAYMENT_PROOF phase (HITL disabled mode)
    if dialog_phase == "WAITING_FOR_PAYMENT_PROOF":
        return await _handle_delivery_data(state, runner, session_id)

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
    products = await hydrate_prices(products, session_id=session_id)
    total_price = sum(p.get("price", 0) for p in products)
    product_names = [p.get("name", labels.get("default_product", "Product")) for p in products]

    # Get user message
    from .utils import extract_user_message
    user_message = extract_user_message(state.get("messages", [])) or labels.get(
        "default_action",
        "Checkout",
    )

    # Create deps with payment context
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
    deps.selected_products = products
    
    metadata = state.get("metadata", {})
    deps.payment_sub_phase = get_payment_sub_phase(metadata)

    try:
        response = await run_payment(
            message=user_message,
            deps=deps,
            message_history=state.get("messages", [])
        )
        response_text = response.reply_to_user
    except Exception as e:
        logger.error("Payment LLM call failed: %s", e)
        response_text = _get_snippet_text(
            "PAYMENT_WAITING_DELIVERY",
            "Please provide delivery details.",
        )
        price_tmpl = get_snippet_by_header("PAYMENT_TOTAL_PRICE_TEMPLATE")
        if price_tmpl:
            response_text += "\n\n" + price_tmpl[0].format(
                total=total_price,
                currency=labels.get("currency_uah", "UAH"),
            )
        else:
            response_text += (
                f"\n\nTotal to pay: {total_price} {labels.get('currency_uah', 'UAH')}"
            )

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

    return Command(
        update={
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "messages": [{"role": "assistant", "content": response_text}],
            "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
            "awaiting_human_approval": True,
            "approval_type": "payment",
            "approval_data": approval_request,
            "human_approved": human_response,
            "selected_products": products,
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="payment",
    )


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
        
        # ⚠️ QUALITY CONTROL: Check payment_quality_check before showing requisites
        if response.payment_quality_check:
            qc = response.payment_quality_check
            ready_for_payment = qc.get("ready_for_payment", False)
            validation_errors = qc.get("validation_errors", [])
            missing_fields = qc.get("missing_fields", [])
            
            # If quality check says NOT ready, don't proceed to requisites
            if not ready_for_payment:
                if validation_errors:
                    logger.warning(
                        "[SESSION %s] Payment quality check failed: %s",
                        session_id,
                        validation_errors,
                    )
                    # Ask for clarification instead of showing requisites
                    if missing_fields:
                        response.reply_to_user = (
                            f"Потрібно уточнити: {', '.join(missing_fields)}.\n\n"
                            + response.reply_to_user
                        )
                # Store quality check in metadata for observability
                metadata["payment_quality_check"] = qc
        
        # Validation & Normalization
        if deps.customer_phone:
            valid = validate_phone_number(deps.customer_phone)
            if valid:
                metadata["customer_phone"] = valid
            else:
                fallback = get_snippet_by_header("PAYMENT_INVALID_PHONE_FALLBACK")
                labels_json = get_snippet_by_header("VISION_LABELS")
                labels = json.loads(labels_json[0]) if labels_json else {}
                response.reply_to_user = (
                    (fallback[0] if fallback else labels.get("invalid_phone", "Invalid phone number"))
                    + "\n\n"
                    + response.reply_to_user
                )

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


async def _handle_approval_response(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["upsell", "end", "validation"]]:
    """Process human approval and CRM submission."""
    approved = state.get("human_approved")
    approval_data = state.get("approval_data", {})
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
