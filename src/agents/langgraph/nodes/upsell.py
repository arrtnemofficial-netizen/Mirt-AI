"""
Upsell Node - Additional sales opportunity.
==========================================
After payment confirmation, offer complementary products.
Uses run_support directly with upsell context.
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
from src.services.observability import log_agent_step, track_metric
from src.services.notifications import NotificationService
from src.core.fallbacks import get_thank_you_message, get_subscribe_message
import re


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents.pydantic.models import SupportResponse


logger = logging.getLogger(__name__)


def _build_crm_status_message(state: dict[str, Any]) -> str:
    """Build CRM status message for user display."""
    crm_order_result = state.get("crm_order_result", {})

    if not crm_order_result:
        return ""

    status = crm_order_result.get("status", "unknown")
    crm_order_id = crm_order_result.get("crm_order_id")
    task_id = crm_order_result.get("task_id")

    if status == "queued":
        message = "🔄 Замовлення відправлено до CRM системи"
        if task_id:
            message += f" (завдання #{task_id[:8]}...)"
        message += "\n✅ Очікуємо підтвердження від оператора"
    elif status == "created":
        message = "✅ Замовлення успішно створено в CRM"
        if crm_order_id:
            message += f" (№{crm_order_id})"
    elif status == "exists":
        message = "ℹ️ Замовлення вже існує в CRM"
        if crm_order_id:
            message += f" (№{crm_order_id})"
    elif status == "failed":
        error = crm_order_result.get("error", "Невідома помилка")
        message = f"⚠️ Проблема з створенням замовлення в CRM: {error}"
    else:
        message = f"📋 Статус замовлення в CRM: {status}"

    return message


async def upsell_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,  # Kept for signature compatibility
) -> dict[str, Any]:
    """
    Offer additional products after payment confirmation.

    This is a soft upsell - suggest, don't push.

    Args:
        state: Current conversation state
        runner: IGNORED - uses run_support directly

    Returns:
        State update with upsell response
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    trace_id = state.get("trace_id", "")

    # Get user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message

    user_message = extract_user_message(state.get("messages", []))
    if not user_message:
        user_message = "Замовлення оформлено"

    # Get current order for context
    ordered_products = state.get("offered_products", []) or state.get("selected_products", [])

    # Check CRM order status and build status message
    crm_status_message = _build_crm_status_message(state)

    # Create deps with upsell context
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_6_UPSELL.value
    deps.selected_products = ordered_products

    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_entry(
            session_id=session_id,
            node_name="upsell",
            phase=state.get("dialog_phase", "?"),
            state_name=State.STATE_6_UPSELL.value,
            extra={
                "products": str(len(ordered_products)),
                "msg": user_message,
            },
        )

    logger.info("Upsell node for session %s", session_id)

    # REJECTION DETECTION (Regex)
    # Check for simple refusal phrases to show Thanks + Subscribe immediately
    # Regex covers: "ні", "не", "не треба", "дякую", "ні дякую", "все"
    rejection_pattern = r"^(ні|нi|не|не треба|не хочу|дякую|спасибі|тільки це|все)\W*$"
    is_refusal = bool(re.match(rejection_pattern, user_message.strip().lower()))

    notifier = NotificationService()

    if is_refusal:
        # HUMAN REFUSED UPSELL -> THANKS + SUBSCRIBE + COMPLETED
        thank_you_text = get_thank_you_message()
        subscribe_text = get_subscribe_message()
        
        assistant_content = f"{thank_you_text}\n\n{subscribe_text}"
        msgs = [{"role": "assistant", "content": m} for m in [thank_you_text, subscribe_text]]

        # Send notification (Silent info)
        try:
            await notifier.send_escalation_alert(
                session_id=session_id,
                reason="Замовлення оформлено (Upsell Refused)",
                user_context=f"Refused Upsell: {user_message}",
                details={"status": "confirmed_no_upsell"},
            )
        except Exception:
            pass

        return {
            "current_state": State.STATE_7_END.value,
            "messages": msgs,
            "agent_response": {
                "event": "order_confirmed",
                "messages": [{"type": "text", "content": m} for m in [thank_you_text, subscribe_text]],
                "metadata": {"session_id": session_id, "intent": "UPSELL_REFUSED", "escalation_level": "NONE"},
            },
            "selected_products": ordered_products,
            "offered_products": ordered_products,
            "dialog_phase": "COMPLETED",
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
        }

    else:
        # USER INTERESTED -> RUN SUPPORT + NOTIFY + KEEP ACTIVE
        # Send Notification about active connection
        try:
            await notifier.send_escalation_alert(
                session_id=session_id,
                reason="Клієнт зацікавився Upsell! (Потрібна увага)",
                user_context=f"Upsell Response: {user_message}",
                details={"status": "upsell_active"},
            )
        except Exception:
            pass

        try:
            # Call support agent with upsell context
            response: SupportResponse = await run_support(
                message=user_message,
                deps=deps,
                message_history=None,
            )

            updated_cart = ordered_products
            if response.products:
                merged: list[dict[str, Any]] = []
                seen: set[str] = set()
                for item in [*ordered_products, *[p.model_dump() for p in response.products]]:
                    if not isinstance(item, dict):
                        continue
                    pid = item.get("id")
                    name = str(item.get("name") or "").strip().lower()
                    size = str(item.get("size") or "").strip().lower()
                    color = str(item.get("color") or "").strip().lower()
                    key = f"{pid}:{size}:{color}" if pid else f"{name}:{size}:{color}"
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(item)
                updated_cart = merged

            latency_ms = (time.perf_counter() - start_time) * 1000

            log_agent_step(
                session_id=session_id,
                state=State.STATE_6_UPSELL.value,
                intent=response.metadata.intent,
                event=response.event,
                latency_ms=latency_ms,
                extra={"trace_id": trace_id},
            )
            track_metric("upsell_node_latency_ms", latency_ms)
            track_metric("upsell_offered", 1, {"session_id": session_id})

            # Build assistant message from response
            assistant_content = "\n".join(m.content for m in response.messages)

            # Prepend CRM status message if available
            if crm_status_message:
                assistant_content = f"{crm_status_message}\n\n{assistant_content}"

            # =====================================================
            # DIALOG PHASE: ACTIVE (NOT COMPLETED)
            # =====================================================
            # User is engaged, keep bot running.
            # State remains STATE_6 or moves to STATE_7 but Phase is ACTIVE.
            # Using STATE_6_UPSELL to keep context.
            # =====================================================
            if settings.DEBUG_TRACE_LOGS:
                debug_log.node_exit(
                    session_id=session_id,
                    node_name="upsell",
                    goto="memory_update",
                    new_phase="ACTIVE",
                    response_preview=assistant_content,
                )
            return {
                "current_state": State.STATE_6_UPSELL.value, # Stay in Upsell/Active state
                "messages": [{"role": "assistant", "content": assistant_content}],
                "metadata": response.metadata.model_dump(),
                "agent_response": response.model_dump(),
                "selected_products": updated_cart,
                "offered_products": updated_cart,
                "dialog_phase": "ACTIVE", # Keep bot alive
                "step_number": state.get("step_number", 0) + 1,
                "last_error": None,
            }

        except Exception as e:
            logger.exception("Upsell node failed for session %s: %s", session_id, e)

            if settings.DEBUG_TRACE_LOGS:
                debug_log.error(
                    session_id=session_id,
                    error_type=type(e).__name__,
                    message=str(e) or type(e).__name__,
                )

            # Non-critical - just skip upsell on error
            return {
                "current_state": State.STATE_7_END.value,
                "dialog_phase": "COMPLETED",
                "step_number": state.get("step_number", 0) + 1,
            }
