# helpers/payment/delivery.py
"""
Delivery data handling - Process user's delivery info and payment proof.

SIMPLIFIED ARCHITECTURE:
- Prompts handle: data collection, confirmation, requisites display
- Code handles: payment proof detection, DB persist, routing

This file delegates behavior to LLM+prompts (STATE_5_PAYMENT_DELIVERY_*.md)
and only implements deterministic guards and infrastructure.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from langgraph.types import Command

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.payment_agent import run_payment
from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.services.observability import log_agent_step

from .utils import ensure_prices_from_catalog
from .crm import persist_order_and_queue_crm

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


async def handle_delivery_data(
    state: dict[str, Any],
    runner: Callable[..., Any] | None,
    session_id: str,
) -> Command[Literal["upsell", "end", "agent"]]:
    """
    Handle delivery data in STATE_5.
    
    FLOW:
    1. Detect payment proof (deterministic)
    2. If proof → persist order → upsell/end
    3. If no proof → delegate to LLM (prompts handle sub-phases)
    """
    from src.agents.langgraph.nodes.utils import extract_user_message
    from src.agents.langgraph.rules.payment_proof import detect_payment_proof

    user_message = extract_user_message(state.get("messages", []))
    products = state.get("selected_products", []) or state.get("offered_products", [])
    products = await ensure_prices_from_catalog(products, session_id=session_id)

    # Detect proof signals
    has_image = bool(
        state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
    )
    has_url = bool(
        user_message and ("http://" in user_message.lower() or "https://" in user_message.lower())
    )

    logger.info(
        "[SESSION %s] Delivery handler: message='%s' (image=%s, url=%s)",
        session_id,
        (user_message or "")[:50],
        has_image,
        has_url,
    )

    # =========================================================================
    # PAYMENT PROOF DETECTION (Deterministic, cannot be in prompt)
    # =========================================================================
    # КРИТИЧНО: Проверяем product addition intent ПЕРЕД payment proof
    # Если это фото товара - НЕ детектируем как payment proof
    from src.agents.langgraph.rules.product_addition import detect_product_addition_intent
    
    is_product_addition = detect_product_addition_intent(user_message) if user_message else False
    
    if is_product_addition:
        logger.info(
            "[SESSION %s] Product addition detected (not payment proof), delegating to LLM",
            session_id,
        )
        # Это фото товара, не payment proof - делегируем в LLM
        return await _delegate_to_llm(
            state=state,
            runner=runner,
            user_message=user_message,
            products=products,
        )
    
    has_real_proof = detect_payment_proof(
        user_text=user_message or "",
        has_image=has_image,
        has_url=has_url,
    )

    # =========================================================================
    # PATH A: Payment proof received → Persist order → Upsell or End
    # =========================================================================
    if has_real_proof:
        return await _handle_payment_proof_received(
            state=state,
            session_id=session_id,
            products=products,
            has_image=has_image,
        )

    # =========================================================================
    # PATH B: No proof → Delegate to LLM (prompts handle REQUEST/CONFIRM/PAYMENT)
    # =========================================================================
    return await _delegate_to_llm(
        state=state,
        session_id=session_id,
        user_message=user_message,
        products=products,
    )


async def _handle_payment_proof_received(
    state: dict[str, Any],
    session_id: str,
    products: list[dict[str, Any]],
    has_image: bool,
) -> Command[Literal["upsell", "end"]]:
    """Handle successful payment proof detection."""
    trace_id = state.get("trace_id", "")
    metadata_update = state.get("metadata", {}).copy()

    log_agent_step(
        session_id=session_id,
        state=State.STATE_7_END.value,
        intent="PAYMENT_DELIVERY",
        event="payment_proof_received",
        extra={
            "trace_id": trace_id,
            "payment_proof_received": True,
            "payment_proof_via": "image" if has_image else "text",
        },
    )

    # Persist order to DB
    approval_data = {
        "total_price": sum(p.get("price", 0) for p in products),
        "products": [p.get("name", "Товар") for p in products],
    }
    crm_order_result = await persist_order_and_queue_crm(
        state=state,
        session_id=session_id,
        approval_data=approval_data,
    )
    logger.info("[SESSION %s] Order persisted after payment proof", session_id)

    # Send manager notification (non-blocking)
    try:
        from src.services.notifications import NotificationService
        await NotificationService().send_escalation_alert(
            session_id=session_id,
            reason="Оплата підтверджена, замовлення створено",
            user_context="Payment Proof Received",
            details=approval_data,
        )
    except Exception:
        pass

    from src.agents.langgraph.nodes.helpers.vision.snippet_loader import get_snippet_by_header
    from src.agents.langgraph.fsm.policy import determine_response_policy, load_manifest
    from src.core.fallbacks import get_thank_you_message, get_subscribe_message, get_payment_fallback_text
    
    manifest = load_manifest()
    actions = manifest.get("actions", {})
    
    # 1. Thank You message (via manifest)
    thank_you_action = actions.get("PAYMENT_THANK_YOU", {})
    thank_you_header = thank_you_action.get("snippet_header", "Подяка за замовлення")
    thank_you_idempotency_key = thank_you_action.get("idempotency_key", "payment_thank_you_sent")
    
    thank_you_snippets = get_snippet_by_header(thank_you_header)
    if thank_you_snippets:
        thank_you = "\n".join(thank_you_snippets)
    else:
        # Fallback
        thank_you = get_thank_you_message()
    
    # Mark as sent (idempotency)
    metadata_update[thank_you_idempotency_key] = True

    # 2. Subscribe message (via manifest, requires thank_you_sent)
    subscribe_action = actions.get("PAYMENT_SUBSCRIBE_REQUEST", {})
    subscribe_header = subscribe_action.get("snippet_header", "Прохання підписатись (безпека)")
    subscribe_idempotency_key = subscribe_action.get("idempotency_key", "payment_subscribe_sent")
    
    subscribe_snippets = get_snippet_by_header(subscribe_header)
    if subscribe_snippets:
        subscribe = "\n".join(subscribe_snippets)
    else:
        # Fallback
        subscribe = get_subscribe_message()
    
    # Mark as sent (idempotency)
    metadata_update[subscribe_idempotency_key] = True

    # Build sequence of messages
    messages_to_send = [
        {"role": "assistant", "content": thank_you},
        {"role": "assistant", "content": subscribe},
    ]
    
    agent_response_messages = [
        {"type": "text", "content": thank_you},
        {"type": "text", "content": subscribe},
    ]

    # Check for upsell opportunity
    upsell_message = _check_upsell_opportunity(products, metadata_update)

    if upsell_message:
        messages_to_send.append({"role": "assistant", "content": upsell_message})
        agent_response_messages.append({"type": "text", "content": upsell_message})
        
        target_state = State.STATE_6_UPSELL.value
        target_phase = "UPSELL_OFFERED"
        target_goto = "upsell"
        intent = "UPSELL_OFFERED"
    else:
        target_state = State.STATE_7_END.value
        target_phase = "COMPLETED"
        target_goto = "end"
        intent = "PAYMENT_DELIVERY"

    return Command(
        update={
            "current_state": target_state,
            "messages": messages_to_send,
            "agent_response": {
                "event": "order_confirmed" if target_goto == "end" else "upsell_offer",
                "messages": agent_response_messages,
                "metadata": {
                    "session_id": session_id,
                    "current_state": target_state,
                    "intent": intent,
                    "escalation_level": "NONE",
                },
            },
            "metadata": {
                **metadata_update,
                "payment_proof_received": True,
                "payment_confirmed": True,
                "crm_order_result": crm_order_result,
            },
            "dialog_phase": target_phase,
            "step_number": state.get("step_number", 0) + 1,
        },
        goto=target_goto,
    )


def _check_upsell_opportunity(
    products: list[dict[str, Any]],
    metadata_update: dict[str, Any],
) -> str | None:
    """Check if upsell is available and update metadata."""
    if not products:
        return None

    first_product = products[0]
    product_name = first_product.get("name", "")
    purchased_color = first_product.get("color")

    if not product_name:
        return None

    try:
        from src.agents.langgraph.nodes.helpers.vision.product_colors import get_color_photos_for_upsell

        color_photos, has_more = get_color_photos_for_upsell(
            product_name=product_name,
            exclude_color=purchased_color,
            max_photos=4,
            offset=0,
        )

        if color_photos:
            metadata_update["upsell_colors_available"] = color_photos
            metadata_update["upsell_has_more_colors"] = has_more
            metadata_update["upsell_product_name"] = product_name
            metadata_update["color_gallery_product"] = product_name
            metadata_update["color_gallery_exclude"] = purchased_color
            metadata_update["color_gallery_offset"] = 0
            return "Хочете ще один колір на зміну? Показати доступні кольори?"
    except Exception:
        pass

    return None


async def _delegate_to_llm(
    state: dict[str, Any],
    session_id: str,
    user_message: str | None,
    products: list[dict[str, Any]],
) -> Command[Literal["end"]]:
    """
    Delegate to LLM for all sub-phases.
    
    The correct prompt file (REQUEST/CONFIRM/PAYMENT/THANKS) is selected
    by get_payment_sub_phase() in state_prompts.py based on metadata.
    """
    # Create deps for agent
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
    deps.selected_products = products

    # Get current sub-phase for prompt selection
    # КРИТИЧНО: Используем payment_sub_phase из transition (SSOT), если передан
    # Иначе вычисляем через get_payment_sub_phase (fallback для обратной совместимости)
    if "payment_sub_phase" in state.get("_temp_context", {}):
        # Используем payment_sub_phase из transition (передан из payment_node)
        deps.payment_sub_phase = state["_temp_context"]["payment_sub_phase"]
        logger.debug(
            "[SESSION %s] Using payment_sub_phase from transition (SSOT): %s",
            session_id,
            deps.payment_sub_phase,
        )
    else:
        # Fallback: вычисляем напрямую (для обратной совместимости)
        try:
            from src.agents.langgraph.state_prompts import get_payment_sub_phase
            deps.payment_sub_phase = get_payment_sub_phase(state)
            logger.debug(
                "[SESSION %s] Computed payment_sub_phase directly (fallback): %s",
                session_id,
                deps.payment_sub_phase,
            )
        except Exception:
            deps.payment_sub_phase = None

    logger.debug(
        "[SESSION %s] Delegating to LLM with sub_phase=%s",
        session_id,
        deps.payment_sub_phase,
    )

    try:
        response = await run_payment(
            message=user_message,
            deps=deps,
            message_history=None,
        )
        response_text = response.reply_to_user or ""

        # Update metadata with customer data from response
        metadata_update = state.get("metadata", {}).copy()
        if deps.customer_name:
            metadata_update["customer_name"] = deps.customer_name
        if deps.customer_phone:
            metadata_update["customer_phone"] = deps.customer_phone
        if deps.customer_city:
            metadata_update["customer_city"] = deps.customer_city
        if deps.customer_nova_poshta:
            metadata_update["customer_nova_poshta"] = deps.customer_nova_poshta

        # Update payment flags from response
        metadata_update["payment_details_sent"] = bool(
            getattr(response, "payment_details_sent", False)
        )
        metadata_update["awaiting_payment_confirmation"] = bool(
            getattr(response, "awaiting_payment_confirmation", False)
        )

        # Split response into bubbles
        response_parts = [p.strip() for p in response_text.split("\n\n") if p.strip()]
        if not response_parts:
            response_parts = [response_text] if response_text else ["Надішліть дані для доставки 🤍"]

        assistant_messages = [{"role": "assistant", "content": p} for p in response_parts]

        cmd = Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": assistant_messages,
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "content": p} for p in response_parts],
                    "metadata": {
                        "session_id": session_id,
                        "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                        "intent": "PAYMENT_DELIVERY",
                        "escalation_level": "NONE",
                    },
                },
                "metadata": metadata_update,
                "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",
        )

        if settings.DEBUG_TRACE_LOGS:
            debug_log.node_exit(
                session_id=session_id,
                node_name="payment",
                goto="end",
                new_phase="WAITING_FOR_PAYMENT_PROOF",
                response_preview=response_text[:100] if response_text else "(empty)",
            )

        return cmd

    except Exception as e:
        logger.error("[SESSION %s] LLM delegation error: %s", session_id, e)
        if settings.DEBUG_TRACE_LOGS:
            debug_log.error(
                session_id=session_id,
                error_type=type(e).__name__,
                message=str(e) or type(e).__name__,
            )

        # Minimal fallback
        return Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": [{"role": "assistant", "content": get_payment_fallback_text()}],
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "content": get_payment_fallback_text()}],
                    "metadata": {
                        "session_id": session_id,
                        "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                        "intent": "PAYMENT_DELIVERY",
                        "escalation_level": "NONE",
                    },
                },
                "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",
        )
