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
from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service
from src.services.catalog_service import CatalogService
from src.services.observability import log_agent_step, track_metric


# State prompts for sub-phases


if TYPE_CHECKING:
    from collections.abc import Callable


logger = logging.getLogger(__name__)


async def _ensure_prices_from_catalog(
    products: list[dict[str, Any]],
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    if not products:
        return products

    catalog = CatalogService()
    cache: dict[str, dict[str, Any]] = {}
    updated: list[dict[str, Any]] = []

    for p in products:
        try:
            price = p.get("price", 0)
            if isinstance(price, (int, float)) and price > 0:
                updated.append(p)
                continue

            name = str(p.get("name") or "").strip()
            size = p.get("size")
            if not name:
                updated.append(p)
                continue

            if name in cache:
                db_product = cache[name]
            else:
                results = await catalog.search_products(query=name, limit=1)
                db_product = results[0] if results else {}
                cache[name] = db_product

            if db_product:
                db_price = CatalogService.get_price_for_size(db_product, size)
                if db_price and db_price > 0:
                    p = {**p, "price": db_price}
        except Exception as e:
            logger.debug("[SESSION %s] Price hydration skipped: %s", session_id, str(e)[:120])

        updated.append(p)

    return updated


PAYMENT_TEMPLATES = {
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
    dialog_phase = state.get("dialog_phase", "")

    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_entry(
            session_id=session_id,
            node_name="payment",
            phase=dialog_phase or "?",
            state_name=state.get("current_state", "?"),
            extra={
                "awaiting": str(bool(state.get("awaiting_human_approval"))),
            },
        )

    # Check if we're resuming from interrupt (HITL enabled)
    if state.get("awaiting_human_approval"):
        return await _handle_approval_response(state, session_id)

    # Check if we're in WAITING_FOR_PAYMENT_PROOF phase (HITL disabled mode)
    # User has sent delivery data or payment proof - process and go to upsell
    if dialog_phase == "WAITING_FOR_PAYMENT_PROOF":
        return await _handle_delivery_data(state, runner, session_id)

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
    products = await _ensure_prices_from_catalog(products, session_id=session_id)
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
        from src.agents.langgraph.state_prompts import get_payment_sub_phase

        deps.payment_sub_phase = get_payment_sub_phase(state)
    except Exception:
        deps.payment_sub_phase = deps.payment_sub_phase

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
        # Lightweight mode: skip human approval interrupt, but WAIT for delivery data
        # User must provide: ПІБ, телефон, адреса НП
        # THEN we go to upsell (after they send payment proof)
        logger.info(
            "[SESSION %s] HITL disabled - waiting for delivery data (ПІБ, адреса, НП)",
            session_id,
        )
        cmd = Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": [{"role": "assistant", "content": response_text}],
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "content": response_text}],
                    "metadata": {
                        "session_id": session_id,
                        "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                        "intent": "PAYMENT_DELIVERY",
                        "escalation_level": "NONE",
                    },
                },
                "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
                "awaiting_human_approval": False,
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",  # WAIT for user to send delivery data, don't skip to upsell!
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

    # This call PAUSES the graph execution
    # It returns ONLY when someone calls graph.invoke(Command(resume=...))
    human_response = interrupt(approval_request)

    # When we get here, human has responded
    # Update state and loop back to process the response
    #
    # DIALOG PHASE: WAITING_FOR_PAYMENT_PROOF
    # - Показали реквізити, чекаємо скрін оплати
    cmd = Command(
        update={
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "messages": [{"role": "assistant", "content": response_text}],
            "agent_response": {
                "event": "simple_answer",
                "messages": [{"type": "text", "content": response_text}],
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
            "human_approved": human_response,  # True/False from human
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="payment",  # Loop back to process approval
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


async def _handle_delivery_data(
    state: dict[str, Any],
    runner: Callable[..., Any] | None,
    session_id: str,
) -> Command[Literal["upsell", "end", "agent"]]:
    """
    Handle delivery data when HITL is disabled.
    
    User has sent their delivery info (ПІБ, phone, НП address).
    We process it through the agent to extract and confirm, then go to upsell.
    """
    from .utils import extract_user_message
    
    user_message = extract_user_message(state.get("messages", []))
    products = state.get("selected_products", []) or state.get("offered_products", [])
    products = await _ensure_prices_from_catalog(products, session_id=session_id)
    total_price = sum(p.get("price", 0) for p in products)

    has_image_now = bool(state.get("has_image", False) or state.get("metadata", {}).get("has_image", False))

    user_text_for_proof = user_message if isinstance(user_message, str) else str(user_message)
    user_text_lower_for_proof = user_text_for_proof.lower()
    payment_confirm_keywords = (
        "оплатила",
        "оплатив",
        "оплачено",
        "переказала",
        "переказав",
        "відправила скрін",
        "відправив скрін",
        "квитанц",
        "скрін",
        "скрин",
        "готово",
    )
    has_payment_url = ("http://" in user_text_lower_for_proof) or ("https://" in user_text_lower_for_proof)
    has_payment_proof_pre = has_image_now or has_payment_url or any(
        k in user_text_lower_for_proof for k in payment_confirm_keywords
    )
    
    logger.info(
        "[SESSION %s] Processing delivery data: '%s'",
        session_id,
        user_message[:50] if user_message else "(empty)",
    )
    
    # Create deps for agent
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
    deps.selected_products = products
    try:
        from src.agents.langgraph.state_prompts import get_payment_sub_phase

        deps.payment_sub_phase = get_payment_sub_phase(state)
        # If we already detect payment proof in this message, force THANK_YOU prompt
        # so the LLM uses STATE_5_PAYMENT_DELIVERY_THANKS (md) as SSOT.
        if has_payment_proof_pre and deps.payment_sub_phase != "THANK_YOU":
            deps.payment_sub_phase = "THANK_YOU"
    except Exception:
        deps.payment_sub_phase = deps.payment_sub_phase
    
    try:
        # Use payment agent to process delivery data
        response = await run_payment(
            message=user_message,
            deps=deps,
            message_history=None,
        )
        response_text = response.reply_to_user

        metadata_update = state.get("metadata", {}).copy()
        if deps.customer_name:
            metadata_update["customer_name"] = deps.customer_name
        if deps.customer_phone:
            metadata_update["customer_phone"] = deps.customer_phone
        if deps.customer_city:
            metadata_update["customer_city"] = deps.customer_city
        if deps.customer_nova_poshta:
            metadata_update["customer_nova_poshta"] = deps.customer_nova_poshta
        metadata_update["payment_details_sent"] = bool(
            getattr(response, "payment_details_sent", False)
        )
        metadata_update["awaiting_payment_confirmation"] = bool(
            getattr(response, "awaiting_payment_confirmation", False)
        )

        user_text = user_message if isinstance(user_message, str) else str(user_message)
        user_text_lower = user_text.lower()

        existing_delivery_data = bool(
            metadata_update.get("customer_name")
            and metadata_update.get("customer_phone")
            and metadata_update.get("customer_city")
            and metadata_update.get("customer_nova_poshta")
        )

        has_delivery_data = bool(
            existing_delivery_data
            or (
                deps.customer_name
                and deps.customer_phone
                and deps.customer_city
                and deps.customer_nova_poshta
            )
        )

        has_payment_proof = has_payment_proof_pre

        confirmation_only_keywords = (
            "да",
            "так",
            "ок",
            "okay",
            "согласен",
            "згоден",
            "беру",
        )

        if user_text_lower.strip() in confirmation_only_keywords and not has_payment_proof:
            missing = []
            if not metadata_update.get("customer_name"):
                missing.append("📝 ПІБ")
            if not metadata_update.get("customer_phone"):
                missing.append("📱 Телефон")
            if not metadata_update.get("customer_city"):
                missing.append("🏙️ Місто")
            if not metadata_update.get("customer_nova_poshta"):
                missing.append("📍 Відділення Нової пошти")

            if missing:
                response_text = "Будь ласка, надішліть:\n" + "\n".join(missing)
            else:
                response_text = "Надішліть, будь ласка, скрін квитанції після оплати 🤍"

        if has_delivery_data and has_payment_proof:
            trace_id = state.get("trace_id", "")
            log_agent_step(
                session_id=session_id,
                state=State.STATE_7_END.value,
                intent="PAYMENT_DELIVERY",
                event="payment_proof_received",
                extra={
                    "trace_id": trace_id,
                    "payment_proof_received": True,
                    "payment_proof_via": "image" if has_image_now else ("url" if has_payment_url else "text"),
                },
            )
            cmd = Command(
                update={
                    "current_state": State.STATE_7_END.value,
                    "messages": [
                        {
                            "role": "assistant",
                            "content": response_text or PAYMENT_TEMPLATES["THANK_YOU"],
                        }
                    ],
                    "agent_response": {
                        "event": "escalation",
                        "messages": [
                            {
                                "type": "text",
                                "content": response_text or PAYMENT_TEMPLATES["THANK_YOU"],
                            }
                        ],
                        "metadata": {
                            "session_id": session_id,
                            "current_state": State.STATE_7_END.value,
                            "intent": "PAYMENT_DELIVERY",
                            "escalation_level": "L1",
                        },
                        "escalation": {
                            "reason": "ORDER_CONFIRMED_ASSIGN_MANAGER",
                            "target": "order_manager",
                        },
                    },
                    "metadata": {
                        **metadata_update,
                        "payment_proof_received": True,
                        "payment_confirmed": True,
                    },
                    "dialog_phase": "COMPLETED",
                    "should_escalate": True,
                    "escalation_reason": "ORDER_CONFIRMED_ASSIGN_MANAGER",
                    "step_number": state.get("step_number", 0) + 1,
                },
                goto="end",
            )
            if settings.DEBUG_TRACE_LOGS:
                debug_log.node_exit(
                    session_id=session_id,
                    node_name="payment",
                    goto=cmd.goto,
                    new_phase="COMPLETED",
                    response_preview=response_text or PAYMENT_TEMPLATES["THANK_YOU"],
                )
            return cmd

        cmd = Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": [{"role": "assistant", "content": response_text}],
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "content": response_text}],
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
                goto=cmd.goto,
                new_phase="WAITING_FOR_PAYMENT_PROOF",
                response_preview=response_text,
            )
        return cmd
            
    except Exception as e:
        logger.error("[SESSION %s] Delivery data processing error: %s", session_id, e)
        if settings.DEBUG_TRACE_LOGS:
            debug_log.error(
                session_id=session_id,
                error_type=type(e).__name__,
                message=str(e) or type(e).__name__,
            )
        # Fallback - ask for data again
        return Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": [{"role": "assistant", "content": 
                    "Будь ласка, надішліть:\n📝 ПІБ\n📱 Телефон\n🏙️ Місто та відділення НП"
                }],
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [
                        {
                            "type": "text",
                            "content": "Будь ласка, надішліть:\n📝 ПІБ\n📱 Телефон\n🏙️ Місто та відділення НП",
                        }
                    ],
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


async def _persist_order_and_queue_crm(
    *,
    state: dict[str, Any],
    session_id: str,
    approval_data: dict[str, Any],
) -> dict[str, Any] | None:
    crm_order_result = None
    try:
        deps = create_deps_from_state(state)

        # Construct order payload
        products = state.get("selected_products", [])
        products = await _ensure_prices_from_catalog(products, session_id=session_id)
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
            "user_nickname": deps.user_nickname,
            "customer": {
                "full_name": deps.customer_name,
                "phone": deps.customer_phone,
                "city": deps.customer_city,
                "nova_poshta_branch": deps.customer_nova_poshta,
                "telegram_id": session_id if "telegram" in str(deps.user_id) else None,
                "manychat_id": session_id if "manychat" in str(deps.user_id) else None,
                "username": deps.user_nickname,
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
        # IDEMPOTENCY: Deterministic external_id based on session + products + price
        # This prevents duplicate orders on retries
        import hashlib

        products_str = "|".join(sorted(p.get("name", "") for p in products))
        idempotency_data = f"{session_id}|{products_str}|{int(approval_data.get('total_price', 0) * 100)}"
        idempotency_hash = hashlib.sha256(idempotency_data.encode()).hexdigest()[:16]
        deterministic_external_id = f"{session_id}_{idempotency_hash}"

        from src.integrations.crm.crmservice import get_crm_service

        crm_service = get_crm_service()
        crm_order_result = await crm_service.create_order_with_persistence(
            session_id=session_id,
            order_data=order_data,
            external_id=deterministic_external_id,
        )

        logger.info(
            "CRM order creation result for session %s: %s",
            session_id,
            crm_order_result.get("status", "unknown"),
        )

    except Exception as e:
        logger.exception("CRITICAL: Failed to save order to DB or queue CRM: %s", e)
        crm_order_result = {"status": "failed", "error": str(e)}

    return crm_order_result


async def _handle_approval_response(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["upsell", "end", "validation"]]:
    """Handle the human's approval response."""

    approved = state.get("human_approved")
    approval_data = state.get("approval_data", {})
    trace_id = state.get("trace_id", "")

    log_agent_step(
        session_id=session_id,
        state=State.STATE_5_PAYMENT_DELIVERY.value,
        intent="PAYMENT_DELIVERY",
        event="payment_approval",
        extra={
            "trace_id": trace_id,
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
        crm_order_result = await _persist_order_and_queue_crm(
            state=state,
            session_id=session_id,
            approval_data=approval_data,
        )

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
