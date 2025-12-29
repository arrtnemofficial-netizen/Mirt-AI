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
from src.services.catalog import CatalogService
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

    # Get payment sub-phase for observability and correct phase mapping
    from src.agents.langgraph.state_prompts import get_payment_sub_phase
    payment_sub_phase = get_payment_sub_phase(state)

    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_entry(
            session_id=session_id,
            node_name="payment",
            phase=dialog_phase or "?",
            state_name=state.get("current_state", "?"),
            extra={
                "awaiting": str(bool(state.get("awaiting_human_approval"))),
                "payment_sub_phase": payment_sub_phase,
            },
        )

    # Observability: Log payment_sub_phase vs dialog_phase for mismatch detection
    logger.info(
        "[SESSION %s] Payment node: dialog_phase=%s, payment_sub_phase=%s",
        session_id,
        dialog_phase,
        payment_sub_phase,
    )

    # Detect phase mismatch (potential bug indicator)
    if dialog_phase == "WAITING_FOR_PAYMENT_PROOF" and payment_sub_phase not in ("SHOW_PAYMENT", "THANK_YOU"):
        logger.warning(
            "[SESSION %s] Phase mismatch detected: dialog_phase=WAITING_FOR_PAYMENT_PROOF but payment_sub_phase=%s",
            session_id,
            payment_sub_phase,
        )
        track_metric("payment_phase_mismatch", 1, {"session_id": session_id, "sub_phase": payment_sub_phase})

    # =========================================================================
    # SNIPPETS-FIRST POLICY: Check for predefined snippets before LLM
    # =========================================================================
    # This handles: "no" responses, payment problems, off-topic questions
    from src.agents.langgraph.nodes.helpers.policy_snippets import maybe_apply_snippet_policy

    from .utils import extract_user_message

    user_message = extract_user_message(state.get("messages", []))
    detected_intent = state.get("detected_intent")

    snippet_response = maybe_apply_snippet_policy(
        state,
        detected_intent=detected_intent,
        user_text=user_message,
    )

    if snippet_response:
        # Snippet found - return response without LLM call
        # Check if we need to notify manager
        should_notify = snippet_response.get("agent_response", {}).get("metadata", {}).get("should_notify_manager", False)

        if should_notify:
            # Notify manager for "no" in payment proof phase or payment problems
            try:
                from src.services.notifications import NotificationService

                notifier = NotificationService()
                reason = "Клієнт сказав 'ні' під час оплати" if "user_says_no" in str(snippet_response.get("metadata", {}).get("policy_case", "")) else "Проблема з оплатою"

                details = {
                    "trace_id": state.get("trace_id"),
                    "dialog_phase": dialog_phase,
                    "current_state": state.get("current_state", "STATE_5_PAYMENT_DELIVERY"),
                    "intent": detected_intent,
                    **state.get("metadata", {}),
                }

                # Provide product summary (for manager context)
                try:
                    products = state.get("selected_products", []) or state.get("offered_products", [])
                    details["products"] = [p if isinstance(p, dict) else p.model_dump() if hasattr(p, "model_dump") else {} for p in products]
                except Exception:
                    details["products"] = []

                await notifier.send_escalation_alert(
                    session_id=session_id,
                    reason=reason,
                    user_context=user_message,
                    details=details,
                )
            except Exception as notify_exc:
                logger.warning(
                    "Manager notification failed for session %s: %s",
                    session_id,
                    str(notify_exc)[:200],
                )

        # Return snippet response (continues dialogue, doesn't break FSM)
        return Command(
            update={
                **snippet_response,
                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
            },
            goto="escalation" if snippet_response.get("should_escalate") else "end",
        )

    # Check if we're resuming from interrupt (HITL enabled)
    if state.get("awaiting_human_approval"):
        return await _handle_approval_response(state, session_id)

    # Check if we're in WAITING_FOR_PAYMENT_PROOF phase (HITL disabled mode)
    # User has sent delivery data or payment proof - process and go to upsell
    if dialog_phase == "WAITING_FOR_PAYMENT_PROOF":
        return await _handle_delivery_data(state, runner, session_id)

    # Check if we're in WAITING_FOR_PAYMENT_METHOD phase
    # User needs to choose payment method (full payment vs prepayment)
    if dialog_phase == "WAITING_FOR_PAYMENT_METHOD":
        return await _handle_payment_method_selection(state, runner, session_id)

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

        # CRITICAL: Determine correct dialog_phase based on payment_sub_phase
        # This prevents setting WAITING_FOR_PAYMENT_PROOF when we're still collecting data
        from src.agents.langgraph.state_prompts import (
            get_payment_sub_phase,
        )

        payment_sub_phase = get_payment_sub_phase(state)

        # Map payment_sub_phase to dialog_phase deterministically
        phase_map = {
            "REQUEST_DATA": "WAITING_FOR_DELIVERY_DATA",  # FIXED: No delivery data yet, need to collect
            "CONFIRM_DATA": "WAITING_FOR_PAYMENT_METHOD",  # Data collected, need payment method choice
            "SHOW_PAYMENT": "WAITING_FOR_PAYMENT_PROOF",  # Requisites shown, waiting for screenshot
            "THANK_YOU": "COMPLETED",
        }
        correct_dialog_phase = phase_map.get(payment_sub_phase, "WAITING_FOR_DELIVERY_DATA")

        # Reset policy counters if dialog phase changed
        old_dialog_phase = state.get("dialog_phase", "")
        if old_dialog_phase != correct_dialog_phase:
            from src.agents.langgraph.nodes.helpers.policy_snippets import _reset_policy_counters
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
                "dialog_phase": correct_dialog_phase,
                "awaiting_human_approval": False,
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",  # WAIT for user input, don't skip to upsell!
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


async def _handle_payment_method_selection(
    state: dict[str, Any],
    runner: Callable[..., Any] | None,
    session_id: str,
) -> Command[Literal["end", "payment"]]:
    """
    Handle payment method selection (full payment vs prepayment).
    
    User has chosen payment method ("Повна оплата" / "Передплата").
    We show requisites and transition to WAITING_FOR_PAYMENT_PROOF.
    """
    from .utils import extract_user_message

    user_message = extract_user_message(state.get("messages", []))
    products = state.get("selected_products", []) or state.get("offered_products", [])
    products = await _ensure_prices_from_catalog(products, session_id=session_id)
    total_price = sum(p.get("price", 0) for p in products)

    # Create deps with payment context
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
    deps.selected_products = products

    # Set sub-phase to SHOW_PAYMENT (we're about to show requisites)
    try:
        deps.payment_sub_phase = "SHOW_PAYMENT"
    except Exception:
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
        # Fallback: show requisites directly
        from src.conf.payment_config import format_requisites_with_receipt_request
        requisites_parts = format_requisites_with_receipt_request(price=int(total_price))
        response_text = "\n\n".join(requisites_parts)
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

    dialog_phase = state.get("dialog_phase", "")

    # =====================================================
    # SNIPPETS-FIRST POLICY: Check snippets BEFORE keywords
    # =====================================================
    # For product addition WITHOUT photo → snippet response
    if not has_image_now and dialog_phase == "WAITING_FOR_PAYMENT_PROOF":
        from src.agents.langgraph.nodes.helpers.policy_snippets import maybe_apply_snippet_policy

        snippet_result = maybe_apply_snippet_policy(
            state=state,
            user_text=user_message,
            detected_intent="PRODUCT_ADDITION",
        )

        if snippet_result and snippet_result.get("agent_response"):
            logger.info(
                "[SESSION %s] Snippets-first: product addition snippet applied (no photo)",
                session_id,
            )
            return Command(
                update={
                    "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                    "messages": [
                        {"role": "assistant", "content": snippet_result["agent_response"]["messages"][0]["content"]}
                    ],
                    "agent_response": snippet_result["agent_response"],
                    "metadata": snippet_result.get("metadata", state.get("metadata", {})).copy(),
                    "dialog_phase": snippet_result.get("dialog_phase", dialog_phase),
                    "step_number": state.get("step_number", 0) + 1,
                },
                goto="end",
            )

    # PHASE-AWARE IMAGE HANDLING: If image is sent in payment proof phase,
    # classify it as payment proof vs product photo
    if has_image_now and dialog_phase == "WAITING_FOR_PAYMENT_PROOF":
        from src.agents.langgraph.rules.payment_proof import detect_payment_proof
        from src.agents.langgraph.rules.product_addition import detect_product_addition_intent

        is_payment_proof = detect_payment_proof(
            user_text=user_message or "",
            has_image=True,
            has_url=has_url,
        )

        if not is_payment_proof:
            # Image doesn't look like payment proof - check if it's product addition
            is_product_addition = detect_product_addition_intent(user_message or "")

            if is_product_addition:
                # User wants to add a product - route to agent for processing
                logger.info(
                    "[SESSION %s] Product addition intent detected in payment phase, routing to agent",
                    session_id,
                )
                # Return command that will route to agent node
                # We need to update state to allow agent to handle product addition
                return Command(
                    update={
                        "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                        "messages": [],  # Agent will generate response
                        "agent_response": {
                            "event": "product_addition",
                            "messages": [],
                            "metadata": {
                                "session_id": session_id,
                                "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                                "intent": "PRODUCT_ADDITION",
                                "escalation_level": "NONE",
                            },
                        },
                        "metadata": state.get("metadata", {}).copy(),
                        "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",  # Stay in same phase
                        "step_number": state.get("step_number", 0) + 1,
                    },
                    goto="agent",  # Route to agent to handle product addition
                )

            # Image doesn't look like payment proof and not product addition - ask for clarification
            # WITHOUT resetting the payment flow
            clarification = (
                "Це фото квитанції/скріну оплати? 🤍\n"
                "Якщо так - все добре, обробляю!\n"
                "Якщо це фото товару - надішліть, будь ласка, скрін оплати окремо."
            )
            logger.info(
                "[SESSION %s] Image in payment phase doesn't match proof heuristics, asking clarification",
                session_id,
            )
            return Command(
                update={
                    "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                    "messages": [{"role": "assistant", "content": clarification}],
                    "agent_response": {
                        "event": "clarifying_question",
                        "messages": [{"type": "text", "content": clarification}],
                        "metadata": {
                            "session_id": session_id,
                            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                            "intent": "PAYMENT_DELIVERY",
                            "escalation_level": "NONE",
                        },
                    },
                    "metadata": state.get("metadata", {}).copy(),
                    "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",  # Stay in same phase
                    "step_number": state.get("step_number", 0) + 1,
                },
                goto="end",
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

        # CRITICAL: Persist order ТІЛЬКИ коли є payment proof (скріншот оплати)
        # Замовлення створюється тільки після підтвердження оплати, не на delivery confirmation
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

            # CRITICAL: Persist order ТІЛЬКИ коли є payment proof (скріншот оплати)
            # Замовлення створюється в PostgreSQL + CRM (якщо увімкнено) тільки після підтвердження оплати
            approval_data = {
                "total_price": sum(p.get("price", 0) for p in products),
                "products": [p.get("name", "Товар") for p in products],
            }
            crm_order_result = await _persist_order_and_queue_crm(
                state=state,
                session_id=session_id,
                approval_data=approval_data,
            )
            logger.info(
                "[SESSION %s] Order persisted after payment proof confirmation",
                session_id,
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
        # Order will be persisted only when payment proof is received (has_real_proof=True)
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

        # Get sitniks_chat_id from state if available
        sitniks_chat_id = state.get("sitniks_chat_id") or state.get("metadata", {}).get("sitniks_chat_id")

        order_data = {
            "external_id": session_id,
            "source_id": deps.user_id,
            "user_nickname": deps.user_nickname,
            "sitniks_chat_id": sitniks_chat_id,  # For status updates in Sitniks
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
        # NOTE: Замовлення в PostgreSQL створюється завжди (рядок 1027 вище).
        # Sitniks CRM integration: ТІЛЬКИ статуси чатів (не створення замовлень).
        # Статуси чатів оновлюються через sitniks_chat_service.update_chat_status(),
        # який перевіряє enabled і не падає без API ключа.
        # =========================================================================
        crm_order_result = {"status": "skipped", "reason": "crm_orders_disabled_only_statuses_enabled"}

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
        # CRITICAL: Payment Proof Guard (HITL flow)
        # =========================================================================
        # HITL підтверджує "payment proof валідний", але перевіряємо детерміновано
        # що proof дійсно є (image/URL) перед створенням order
        from src.agents.langgraph.rules.payment_proof import detect_payment_proof

        from .utils import extract_user_message

        user_message = extract_user_message(state.get("messages", []))
        has_image = bool(
            state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
        )
        has_url = bool(
            user_message
            and ("http://" in user_message.lower() or "https://" in user_message.lower())
        )

        has_real_proof = detect_payment_proof(
            user_text=user_message or "",
            has_image=has_image,
            has_url=has_url,
        )

        if not has_real_proof:
            # HITL approved, але payment proof не отримано - чекаємо proof
            logger.warning(
                "[SESSION %s] HITL approved but no payment proof detected. Waiting for proof.",
                session_id,
            )
            return Command(
                update={
                    "awaiting_human_approval": False,
                    "approval_type": None,
                    "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                    "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "Надішліть, будь ласка, скрін або квитанцію оплати 🤍",
                        }
                    ],
                    "agent_response": {
                        "event": "simple_answer",
                        "messages": [
                            {
                                "type": "text",
                                "content": "Надішліть, будь ласка, скрін або квитанцію оплати 🤍",
                            }
                        ],
                        "metadata": {
                            "session_id": session_id,
                            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                            "intent": "PAYMENT_DELIVERY",
                            "escalation_level": "NONE",
                        },
                    },
                    "step_number": state.get("step_number", 0) + 1,
                },
                goto="end",
            )

        # =========================================================================
        # SAVE ORDER TO DB (Persistence) - тільки після підтвердження payment proof
        # =========================================================================
        crm_order_result = await _persist_order_and_queue_crm(
            state=state,
            session_id=session_id,
            approval_data=approval_data,
        )

        # DIALOG PHASE: UPSELL_OFFERED (STATE_6)
        # - Оплата підтверджена, пропонуємо допродаж
        # NOTE: Order is saved in local DB (PostgreSQL) regardless of CRM status
        # CRM orders integration disabled - only chat statuses are supported
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
