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
        # LLM-FIRST: Використовуємо reply_to_user з PaymentResponse
        # PaymentResponse не має messages (тільки reply_to_user), тому використовуємо його
        response_text = response.reply_to_user or ""
    except Exception as e:
        logger.error("Payment LLM call failed: %s", e)
        # Мінімальний fallback - LLM має завжди працювати, fallback тільки для критичних помилок
        response_text = "Для оформлення замовлення надішліть ПІБ, телефон та адресу Нової Пошти 🤍"

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
        # PaymentResponse має тільки reply_to_user, розбиваємо на багатобаблові повідомлення
        # Розбиваємо по подвійних переносах рядків (\n\n) для багатобаблових відповідей
        response_parts = [p.strip() for p in response_text.split("\n\n") if p.strip()]
        assistant_messages = [{"role": "assistant", "content": part} for part in response_parts] if response_parts else [{"role": "assistant", "content": response_text}]
        
        cmd = Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": assistant_messages,
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "content": part} for part in response_parts] if response_parts else [{"type": "text", "content": response_text}],
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
    # PaymentResponse має тільки reply_to_user, розбиваємо на багатобаблові повідомлення
    response_parts = [p.strip() for p in response_text.split("\n\n") if p.strip()]
    assistant_messages = [{"role": "assistant", "content": part} for part in response_parts] if response_parts else [{"role": "assistant", "content": response_text}]
    
    cmd = Command(
        update={
            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            "messages": assistant_messages,
            "agent_response": {
                "event": "simple_answer",
                "messages": [{"type": "text", "content": part} for part in response_parts] if response_parts else [{"type": "text", "content": response_text}],
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

    has_image_now = bool(
        state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
    )

    # Check for URL in message (payment proof link)
    has_url = bool(
        user_message
        and ("http://" in user_message.lower() or "https://" in user_message.lower())
    )

    # -------------------------------------------------------------------------
    # Deterministic guard: short "yes/ok" without proof should NOT be treated as
    # payment proof or be passed through as "Ок". Ask for screenshot/receipt.
    # (Matches unit tests and prevents bot-like acknowledgements.)
    # -------------------------------------------------------------------------
    um = (user_message or "").strip().lower()
    if not has_image_now and not has_url and um in {"так", "да", "ок", "окей"}:
        prompt = "Надішліть, будь ласка, скрін або квитанцію оплати 🤍"
        return Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": [{"role": "assistant", "content": prompt}],
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "content": prompt}],
                    "metadata": {
                        "session_id": session_id,
                        "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                        "intent": "PAYMENT_DELIVERY",
                        "escalation_level": "NONE",
                    },
                },
                "metadata": state.get("metadata", {}).copy(),
                "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",
        )

    logger.info(
        "[SESSION %s] Processing delivery data: '%s' (has_image=%s, has_url=%s)",
        session_id,
        user_message[:50] if user_message else "(empty)",
        has_image_now,
        has_url,
    )

    # Create deps for agent
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
    deps.selected_products = products
    
    # LLM-FIRST: Дозволяємо LLM самому визначати sub-phase через промпти
    # Не форсуємо THANK_YOU через detect_payment_proof - LLM сам визначить через контекст
    try:
        from src.agents.langgraph.state_prompts import get_payment_sub_phase
        deps.payment_sub_phase = get_payment_sub_phase(state)
    except Exception:
        deps.payment_sub_phase = None

    try:
        # Use payment agent to process delivery data
        response = await run_payment(
            message=user_message,
            deps=deps,
            message_history=None,
        )
        # LLM-FIRST: Використовуємо reply_to_user з PaymentResponse
        # PaymentResponse не має messages (тільки reply_to_user), тому використовуємо його
        # Legacy код який перезаписував response_text видалено - дозволяємо LLM генерувати відповіді
        response_text = response.reply_to_user or ""

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

        # LLM-FIRST: Використовуємо тільки поля з PaymentResponse для бізнес-логіки
        # LLM сам визначає через промпти:
        # - order_ready: чи готове замовлення (всі дані + payment proof)
        # - missing_fields: які дані ще потрібні
        # - awaiting_payment_confirmation: чи чекаємо скрін оплати
        # - payment_details_sent: чи надіслано реквізити
        
        # PAYMENT-PROOF GUARD: Перевіряємо детерміновано чи є реальний proof перед переходом до THANKS
        # Це запобігає передчасним "Дякую за оплату" без реального скріну/квитанції
        from src.agents.langgraph.rules.payment_proof import detect_payment_proof
        
        has_real_proof = detect_payment_proof(
            user_text=user_message or "",
            has_image=has_image_now,
            has_url=has_url,
        )
        
        # Переходимо до STATE_7_END тільки якщо:
        # 1. LLM визначив що order_ready=True (всі дані зібрані)
        # 2. І є реальний payment proof (скрін/квитанція/URL)
        if response.order_ready and has_real_proof:
            trace_id = state.get("trace_id", "")
            log_agent_step(
                session_id=session_id,
                state=State.STATE_7_END.value,
                intent="PAYMENT_DELIVERY",
                event="payment_proof_received",
                extra={
                    "trace_id": trace_id,
                    "payment_proof_received": True,
                    "payment_proof_via": "image" if has_image_now else "text",
                },
            )
            
            # Persist order; CRM queueing is optional (should not block UX).
            approval_data = {
                "total_price": sum(p.get("price", 0) for p in products),
                "products": [p.get("name", "Товар") for p in products],
            }
            crm_order_result = await _persist_order_and_queue_crm(
                state=state,
                session_id=session_id,
                approval_data=approval_data,
            )
            
            # CRM створено успішно - переходимо до STATE_7_END з THANKS + UPSELL
            # БАБЛ 1: Подяка
            thank_you_text = response_text or PAYMENT_TEMPLATES["THANK_YOU"]
            # Розбиваємо на частини якщо є подвійні переноси
            thank_you_parts = [p.strip() for p in thank_you_text.split("\n\n") if p.strip()]
            if not thank_you_parts:
                thank_you_parts = [thank_you_text]
            
            # БАБЛ 2: Upsell про другий колір (якщо є інші кольори)
            upsell_messages = []
            if products:
                # Беремо перший продукт для upsell
                first_product = products[0]
                product_name = first_product.get("name", "")
                purchased_color = first_product.get("color")
                
                if product_name:
                    from .helpers.vision.product_colors import get_color_photos_for_upsell
                    
                    color_photos, has_more = get_color_photos_for_upsell(
                        product_name=product_name,
                        exclude_color=purchased_color,
                        max_photos=4,
                        offset=0,
                    )
                    
                    if color_photos:
                        upsell_text = "Хочете ще один колір на зміну? Показати доступні кольори?"
                        upsell_messages.append({"type": "text", "content": upsell_text})
                        # Зберігаємо дані про кольори в metadata для майбутнього показу
                        metadata_update["upsell_colors_available"] = color_photos
                        metadata_update["upsell_has_more_colors"] = has_more
                        metadata_update["upsell_product_name"] = product_name
                        metadata_update["color_gallery_product"] = product_name
                        metadata_update["color_gallery_exclude"] = purchased_color
                        metadata_update["color_gallery_offset"] = 0
            
            # Формуємо повідомлення: THANKS + UPSELL
            all_messages = []
            for part in thank_you_parts:
                all_messages.append({"type": "text", "content": part})
            all_messages.extend(upsell_messages)
            
            # Формуємо assistant_messages для state
            assistant_messages = [{"role": "assistant", "content": msg["content"]} for msg in all_messages]
            
            cmd = Command(
                update={
                    "current_state": State.STATE_7_END.value,
                    "messages": assistant_messages,
                    "agent_response": {
                        "event": "escalation",
                        "messages": all_messages,
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
                        "crm_order_result": crm_order_result,
                        "crm_external_id": crm_order_result.get("external_id") if crm_order_result else None,
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

        # PaymentResponse має тільки reply_to_user, розбиваємо на багатобаблові повідомлення
        response_parts = [p.strip() for p in response_text.split("\n\n") if p.strip()]
        assistant_messages = [{"role": "assistant", "content": part} for part in response_parts] if response_parts else [{"role": "assistant", "content": response_text}]

        cmd = Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": assistant_messages,
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "content": part} for part in response_parts] if response_parts else [{"type": "text", "content": response_text}],
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
        # Мінімальний fallback - LLM має завжди працювати
        return Command(
            update={
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                "messages": [
                    {
                        "role": "assistant",
                        "content": "Надішліть, будь ласка, ПІБ, телефон та адресу Нової Пошти 🤍",
                    }
                ],
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [
                        {
                            "type": "text",
                            "content": "Надішліть, будь ласка, ПІБ, телефон та адресу Нової Пошти 🤍",
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
        # CREATE ORDER IN SNITKIX CRM (Optional; must not block tests/UX)
        # =========================================================================
        enable_crm = bool(getattr(settings, "ENABLE_CRM_INTEGRATION", False))
        if enable_crm:
            # IDEMPOTENCY: Deterministic external_id based on session + products + price
            # This prevents duplicate orders on retries
            import hashlib

            products_str = "|".join(sorted(p.get("name", "") for p in products))
            idempotency_data = (
                f"{session_id}|{products_str}|{int(approval_data.get('total_price', 0) * 100)}"
            )
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
        else:
            crm_order_result = {"status": "skipped", "reason": "crm_disabled"}

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
                    "crm_external_id": crm_order_result.get("external_id")
                    if crm_order_result
                    else None,
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
