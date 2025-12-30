"""
Agent Node - Main LLM processing.
=================================
General-purpose agent for discovery, size/color questions.

QUALITY IMPLEMENTATION:
- Детальні промпти для кожного стейту
- Правильна логіка переходів
- Sub-phases для payment
- Intent-based routing
- Multi-bubble responses
"""

from __future__ import annotations

import logging
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from src.agents.langgraph.nodes.intent import INTENT_PATTERNS

# PydanticAI imports
from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.support_agent import run_support
from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.services.catalog import extract_requested_color
from src.services.observability import log_agent_step, log_trace, track_metric

# State prompts and transition logic
from ..state_prompts import (
    determine_next_dialog_phase,
    get_payment_sub_phase,
    get_state_prompt,
)


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents.pydantic.models import SupportResponse


logger = logging.getLogger(__name__)


def _handle_color_show_request(
    user_message: str,
    state: dict[str, Any],
    current_state: str,
) -> dict[str, Any] | None:
    """
    Handle color show request (universal for any state).
    
    Returns state update if handled, None otherwise.
    """
    try:
        from src.agents.langgraph.rules.color_request import (
            detect_color_show_request,
            get_current_color_for_exclusion,
            get_product_name_for_color_show,
        )

        # Перевіряємо чи це запит на показ кольорів або "показати решту"
        is_color_request = detect_color_show_request(user_message)
        is_show_more = (
            user_message.lower().strip() in ["показати решту", "покажи решту", "так", "да", "ок"]
            and state.get("metadata", {}).get("color_gallery_offset") is not None
        )

        if not (is_color_request or is_show_more):
            return None

        product_name = get_product_name_for_color_show(state)
        if not product_name:
            return None

        from src.agents.langgraph.nodes.helpers.vision.product_colors import (
            get_color_photos_for_upsell,
        )

        exclude_color = get_current_color_for_exclusion(state)

        # Якщо це "показати решту" - беремо offset з metadata
        if is_show_more:
            metadata = state.get("metadata", {})
            offset = metadata.get("color_gallery_offset", 0)
            # Оновлюємо product_name та exclude_color з metadata якщо є
            if metadata.get("color_gallery_product"):
                product_name = metadata.get("color_gallery_product")
            if metadata.get("color_gallery_exclude"):
                exclude_color = metadata.get("color_gallery_exclude")
        else:
            offset = 0

        color_photos, has_more = get_color_photos_for_upsell(
            product_name=product_name,
            exclude_color=exclude_color,
            max_photos=4,
            offset=offset,
        )

        if not color_photos:
            return None

        session_id = state.get(
            "session_id", state.get("metadata", {}).get("session_id", "")
        )
        trace_id = state.get("trace_id", "")

        # Формуємо messages: ТІЛЬКИ фото, без зайвого тексту перед ними
        messages = []

        # Додаємо фото (до 4) - БЕЗ тексту перед ними
        for color_photo in color_photos:
            photo_url = color_photo.get("photo_url")
            if photo_url:
                messages.append({"type": "image", "content": photo_url})

        # Якщо є ще кольори - додаємо текст "Показати решту?" ПІСЛЯ фото
        metadata_update = state.get("metadata", {}).copy()
        if has_more:
            messages.append({
                "type": "text",
                "content": "Показати решту кольорів?",
            })
            # Зберігаємо курсор для пагінації
            metadata_update["color_gallery_offset"] = offset + len(color_photos)
            metadata_update["color_gallery_product"] = product_name
            if exclude_color:
                metadata_update["color_gallery_exclude"] = exclude_color
        else:
            # Очищаємо курсор якщо більше немає кольорів
            metadata_update.pop("color_gallery_offset", None)
            metadata_update.pop("color_gallery_product", None)
            metadata_update.pop("color_gallery_exclude", None)

        agent_response_payload = {
            "event": "simple_answer",
            "messages": messages,
            "products": state.get("selected_products", []) or [],
            "metadata": {
                "session_id": session_id,
                "current_state": current_state,
                "intent": "COLOR_HELP",
                "escalation_level": "NONE",
            },
        }

        metadata_update["current_state"] = current_state
        metadata_update["intent"] = "COLOR_HELP"

        assistant_messages = []
        for msg in messages:
            if msg["type"] == "text":
                assistant_messages.append({
                    "role": "assistant",
                    "content": msg["content"],
                })
            elif msg["type"] == "image":
                assistant_messages.append({
                    "role": "assistant",
                    "type": "image",
                    "content": msg["content"],
                })

        with suppress(Exception):
            log_agent_step(
                session_id=session_id,
                state=current_state,
                intent="COLOR_HELP",
                event="color_gallery_shown",
                latency_ms=0.0,
                extra={
                    "trace_id": trace_id,
                    "product_name": product_name,
                    "colors_shown": len(color_photos),
                    "has_more": has_more,
                    "offset": offset,
                },
            )

        return {
            "current_state": current_state,
            "detected_intent": "COLOR_HELP",
            "dialog_phase": state.get("dialog_phase", "WAITING_FOR_COLOR"),
            "messages": assistant_messages,
            "metadata": metadata_update,
            "selected_products": state.get("selected_products", []) or [],
            "should_escalate": False,
            "escalation_reason": None,
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
            "agent_response": agent_response_payload,
        }
    except Exception as e:
        logger.debug("Color show request handler error: %s", e, exc_info=True)
        # Return None to continue normal LLM processing if handler fails
        return None


# Centralized keyword lists for confirmations (used for STATE_4 → STATE_5 safety net)
_CONFIRMATION_BASE = INTENT_PATTERNS.get("CONFIRMATION", [])

_OFFER_CONFIRMATION_KEYWORDS = [
    "беру",
    "оформлюємо",
    "оформляємо",
    "хочу замовити",
    *_CONFIRMATION_BASE,
]


# =============================================================================
# SIZE EXTRACTION HELPER (delegated to helpers module)
# =============================================================================
from .helpers.intent_instructions import get_instructions_for_intent
from .helpers.size_parsing import extract_size_from_response, height_to_size


# Backward compatibility aliases
_height_to_size = height_to_size
_extract_size_from_response = extract_size_from_response
_get_instructions_for_intent = get_instructions_for_intent


async def agent_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """
    General agent node using PydanticAI with proper DI.

    This is the main workhorse node that handles most conversations.
    Uses support_agent with:
    - AgentDeps for dependency injection
    - SupportResponse for structured output

    Args:
        state: Current conversation state
        runner: Legacy runner (ignored, uses PydanticAI)

    Returns:
        State update with structured response
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    trace_id = state.get("trace_id", "")
    current_state = state.get("current_state", State.STATE_0_INIT.value)

    # Get user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message

    user_message = extract_user_message(state.get("messages", []))

    if not user_message:
        return {
            "step_number": state.get("step_number", 0) + 1,
        }

    # =====================================================================
    # SNIPPETS-FIRST POLICY: Check for predefined snippets before LLM
    # =====================================================================
    # This handles: "no" responses, off-topic questions
    from src.agents.langgraph.nodes.helpers.policy_snippets import maybe_apply_snippet_policy

    detected_intent = state.get("detected_intent")
    snippet_response = maybe_apply_snippet_policy(
        state,
        detected_intent=detected_intent,
        user_text=user_message,
    )

    if snippet_response:
        # Snippet found - return response without LLM call
        # Note: Manager notifications for "no" in payment phase are handled in payment_node
        return {
            **snippet_response,
            "step_number": state.get("step_number", 0) + 1,
        }

    # =====================================================================
    # SSOT RESPONSE POLICY CHECK: Если должен быть snippet - НЕ вызываем LLM
    # =====================================================================
    # КРИТИЧНО: Проверяем response_policy ПЕРЕД вызовом LLM
    # Это предотвращает повтор цены после согласия и гарантирует snippet-only ответ
    from src.agents.langgraph.fsm.transition_reducer import compute_transition
    from src.agents.langgraph.fsm.policy import determine_response_policy
    
    # Вычисляем transition для определения response_policy
    transition = compute_transition(
        state=state,
        intent=detected_intent or "DISCOVERY_OR_QUESTION",
        has_image=state.get("has_image", False) or state.get("metadata", {}).get("has_image", False),
        user_message=user_message,
    )
    
    # Проверяем response_policy
    response_policy = determine_response_policy(
        next_state=transition.next_state,
        payment_sub_phase=transition.payment_sub_phase,
        metadata=state.get("metadata", {}),
        session_id=session_id,
    )
    
    # КРИТИЧНО: Если должен быть snippet - НЕ вызываем LLM, возвращаем snippet
    if response_policy.snippet_name and not response_policy.use_llm:
        from src.agents.langgraph.nodes.helpers.vision.snippet_loader import get_snippet_by_header
        
        snippets = get_snippet_by_header(response_policy.snippet_name)
        if snippets:
            snippet_text = "\n\n".join(snippets)
            
            # Устанавливаем флаг idempotency
            metadata_update = state.get("metadata", {}).copy()
            if response_policy.snippet_sent_flag:
                metadata_update[response_policy.snippet_sent_flag] = True
            
            logger.info(
                "[SESSION %s] 🎯 Snippet-only response (no LLM): snippet=%s, flag=%s, next_state=%s",
                session_id,
                response_policy.snippet_name,
                response_policy.snippet_sent_flag,
                transition.next_state,
            )
            
            return {
                "current_state": transition.next_state,
                "dialog_phase": transition.dialog_phase,
                "metadata": metadata_update,
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "content": snippet_text}],
                    "metadata": {
                        "session_id": session_id,
                        "current_state": transition.next_state,
                        "intent": "PAYMENT_DELIVERY" if transition.next_state == State.STATE_5_PAYMENT_DELIVERY.value else detected_intent,
                    },
                },
                "step_number": state.get("step_number", 0) + 1,
            }
        else:
            logger.warning(
                "[SESSION %s] ⚠️ Snippet '%s' not found, falling back to LLM",
                session_id,
                response_policy.snippet_name,
            )
    
    # =====================================================================
    # UNIVERSAL COLOR SHOW REQUEST HANDLER (any state)
    # =====================================================================
    # Якщо клієнт просить показати кольори (в будь-якому стані) - показуємо фото
    # з products_master.yaml з капом 4 фото + "Показати решту?" якщо більше
    # Підтримує пагінацію: якщо клієнт каже "показати решту" - показуємо наступні 4
    # =====================================================================
    color_handler_result = _handle_color_show_request(user_message, state, current_state)
    if color_handler_result is not None:
        return color_handler_result

    # =====================================================================
    # STATE_3_SIZE_COLOR: Specific color validation (existing logic)
    # =====================================================================
    if current_state == State.STATE_3_SIZE_COLOR.value:
        try:
            available_colors = state.get("metadata", {}).get("available_colors")
            if isinstance(available_colors, list) and available_colors:
                requested = extract_requested_color(user_message)
                if requested:

                    def _norm(s: str) -> str:
                        return " ".join((s or "").lower().strip().split())

                    options = [str(c).strip() for c in available_colors if str(c).strip()]
                    option_norms = {_norm(c) for c in options}
                    if option_norms and (_norm(requested) not in option_norms):
                        session_id = state.get(
                            "session_id", state.get("metadata", {}).get("session_id", "")
                        )
                        trace_id = state.get("trace_id", "")

                        options_text = ", ".join(options[:8])
                        reply_text = (
                            f"Такого кольору цієї моделі у нас немає. Є в наявності: {options_text}. 🤍\n"
                            "Який колір обираєте?"
                        )

                        agent_response_payload = {
                            "event": "simple_answer",
                            "messages": [{"type": "text", "content": reply_text}],
                            "products": state.get("selected_products", []) or [],
                            "metadata": {
                                "session_id": session_id,
                                "current_state": current_state,
                                "intent": "COLOR_HELP",
                                "escalation_level": "NONE",
                            },
                        }

                        metadata_update = state.get("metadata", {}).copy()
                        metadata_update["current_state"] = current_state
                        metadata_update["intent"] = "COLOR_HELP"

                        assistant_content = {
                            "event": "simple_answer",
                            "messages": [{"type": "text", "content": reply_text}],
                            "products": [],
                            "metadata": {
                                "session_id": session_id,
                                "current_state": current_state,
                                "intent": "COLOR_HELP",
                                "escalation_level": "NONE",
                            },
                        }

                        with suppress(Exception):
                            log_agent_step(
                                session_id=session_id,
                                state=current_state,
                                intent="COLOR_HELP",
                                event="simple_answer",
                                latency_ms=0.0,
                                extra={"trace_id": trace_id, "blocked_color": requested},
                            )

                        return {
                            "current_state": current_state,
                            "detected_intent": "COLOR_HELP",
                            "dialog_phase": "WAITING_FOR_COLOR",
                            "messages": [{"role": "assistant", "content": str(assistant_content)}],
                            "metadata": metadata_update,
                            "selected_products": state.get("selected_products", []) or [],
                            "should_escalate": False,
                            "escalation_reason": None,
                            "step_number": state.get("step_number", 0) + 1,
                            "last_error": None,
                            "agent_response": agent_response_payload,
                        }
        except Exception:
            pass

    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_entry(
            session_id=session_id,
            node_name="agent",
            phase=state.get("dialog_phase", "?"),
            state_name=current_state,
            extra={
                "intent": state.get("detected_intent"),
                "msg": user_message,
            },
        )

    # =========================================================================
    # HISTORY TRIMMING: Prevent LLM context overflow
    # =========================================================================
    from src.services.conversation import trim_message_history

    original_messages = state.get("messages", [])
    trimmed_messages = trim_message_history(original_messages)

    # Update state with trimmed messages for this LLM call
    # (doesn't affect persisted state, only this invocation)
    state_for_llm = {**state, "messages": trimmed_messages}

    # Create deps from state (proper DI!)
    deps = create_deps_from_state(state_for_llm)

    # =========================================================================
    # QUALITY: Inject state-specific prompt
    # =========================================================================
    # Додаємо детальні інструкції для поточного стейту
    dialog_phase = state.get("dialog_phase", "INIT")
    state_prompt = get_state_prompt(current_state)

    # Для payment додаємо sub-phase prompt
    # КРИТИЧНО: Используем payment_sub_phase из transition (SSOT), а не вызываем get_payment_sub_phase напрямую
    if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        # Используем payment_sub_phase из transition (вычислен выше в response_policy check)
        payment_sub = transition.payment_sub_phase or "REQUEST_DATA"
        state_prompt = get_state_prompt(current_state, payment_sub)
        logger.info(
            "💰 [SESSION %s] Payment sub-phase: %s (from SSOT transition)",
            session_id,
            payment_sub,
        )

    # Inject state prompt into deps for LLM context
    if state_prompt:
        deps.state_specific_prompt = state_prompt
        logger.debug("Injected state prompt for %s (%d chars)", current_state, len(state_prompt))

        if settings.DEBUG_TRACE_LOGS:
            debug_log.prompt_debug(
                session_id=session_id,
                prompt_name=f"state.{current_state}",
                prompt_content=state_prompt,
                variables={
                    "dialog_phase": dialog_phase,
                    "trace_id": trace_id,
                },
            )

    try:
        # Call PydanticAI agent with proper DI
        # КРИТИЧНО: Для STATE_5 используем payment_agent (имеет tool extract_customer_data)
        # Для остальных состояний используем support_agent
        llm_start_time = time.perf_counter()
        
        if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
            # Используем payment_agent для извлечения данных доставки
            from src.agents.pydantic.payment_agent import run_payment
            from src.agents.pydantic.models import PaymentResponse, SupportResponse, MessageItem, ResponseMetadata
            
            payment_response: PaymentResponse = await run_payment(
                message=user_message,
                deps=deps,
                message_history=None,
            )
            
            # Конвертируем PaymentResponse в SupportResponse для совместимости
            # PaymentResponse.reply_to_user -> SupportResponse.messages
            # PaymentResponse.customer_data -> сохраняем в metadata
            messages = [MessageItem(type="text", content=payment_response.reply_to_user)]
            
            # Сохраняем customer_data в metadata для обновления state
            metadata_dict = deps.metadata.model_dump() if hasattr(deps, 'metadata') else {}
            if payment_response.customer_data:
                # Обновляем metadata с данными клиента
                if payment_response.customer_data.name:
                    metadata_dict["customer_name"] = payment_response.customer_data.name
                if payment_response.customer_data.phone:
                    metadata_dict["customer_phone"] = payment_response.customer_data.phone
                if payment_response.customer_data.city:
                    metadata_dict["customer_city"] = payment_response.customer_data.city
                if payment_response.customer_data.nova_poshta:
                    metadata_dict["customer_nova_poshta"] = payment_response.customer_data.nova_poshta
            
            metadata = ResponseMetadata(
                session_id=metadata_dict.get("session_id", session_id),
                current_state=State.STATE_5_PAYMENT_DELIVERY.value,
                intent="PAYMENT_DELIVERY",
                escalation_level="NONE",
            )
            
            response = SupportResponse(
                event="clarifying_question" if payment_response.missing_fields else "simple_answer",
                messages=messages,
                products=[],
                metadata=metadata,
            )
            # КРИТИЧНО: Сохраняем customer_data из PaymentResponse для последующего обновления state
            # Добавляем как атрибут для совместимости с кодом ниже (строка 867)
            response.customer_data = payment_response.customer_data
        else:
            # Для остальных состояний используем support_agent
            response: SupportResponse = await run_support(
                message=user_message,
                deps=deps,
                message_history=None,
            )
        
        llm_latency_ms = (time.perf_counter() - llm_start_time) * 1000.0
        # Track LLM latency metric
        track_metric("llm_latency_ms", llm_latency_ms, {"state": current_state, "intent": response.metadata.intent or "unknown"})

        # DETAILED LOGGING: What did the agent return?
        first_msg = response.messages[0].content[:100] if response.messages else "None"
        logger.info(
            "Agent response for session %s: event=%s, state=%s->%s, intent=%s, products=%d, msg=%s",
            session_id,
            response.event,
            current_state,
            response.metadata.current_state,
            response.metadata.intent,
            len(response.products),
            first_msg,
        )

        vision_greeted_before = bool(state.get("metadata", {}).get("vision_greeted", False))
        if (
            current_state == State.STATE_3_SIZE_COLOR.value
            and vision_greeted_before
            and response.messages
            and len(response.messages) > 1
        ):
            first_content = response.messages[0].content.strip().lower()
            if first_content.startswith("вітаю") or "mirt_ua" in first_content:
                response.messages = response.messages[1:]

        # =====================================================================
        # RUNTIME GUARD: Prevent "blind" PHOTO_IDENT from text-only agent
        # =====================================================================
        # CRITICAL: If photo was NOT processed by vision_node, this agent
        # must NOT claim it analyzed the photo (intent=PHOTO_IDENT).
        # Photos are analyzed by vision_node, not this text-only agent.
        # =====================================================================
        has_image = state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
        intent = response.metadata.intent

        # Check if photo was processed by vision (check metadata for vision indicators)
        metadata = state.get("metadata", {}) or {}
        vision_processed = bool(
            metadata.get("vision_confidence") is not None
            or metadata.get("vision_greeted", False)
            or current_state == State.STATE_2_VISION.value
        )

        # If agent claims PHOTO_IDENT but vision didn't process it, suppress it
        if has_image and intent == "PHOTO_IDENT" and not vision_processed:
            logger.warning(
                "🚨 [SESSION %s] Agent node produced PHOTO_IDENT without vision processing. "
                "Suppressing to DISCOVERY_OR_QUESTION (photo should be handled by vision_node).",
                session_id,
            )
            # from src.services.observability import track_metric  <-- REMOVE
            track_metric(
                "agent_photo_ident_suppressed",
                1,
                {
                    "session_id": session_id,
                    "current_state": current_state,
                    "dialog_phase": state.get("dialog_phase", "UNKNOWN"),
                },
            )
            intent = "DISCOVERY_OR_QUESTION"
            response.metadata.intent = intent

        # =====================================================================
        # LLM-FIRST APPROACH: Trust improved prompts for intent classification
        # =====================================================================
        # The STATE_5 prompts now explicitly teach LLM that "да/так/ок" in
        # payment flow = PAYMENT_DELIVERY, not THANKYOU. LLM should output
        # requisites directly when user confirms data.
        #
        # Previous keyword-override for injecting requisites is REMOVED.
        # If LLM still makes mistakes, improve the prompt, not add patches.
        # =====================================================================

        # Extract from OUTPUT_CONTRACT structure
        new_state_str = response.metadata.current_state
        is_escalation = response.event == "escalation"

        # =====================================================================
        # SSOT: USE TRANSITION REDUCER FOR STATE TRANSITION
        # =====================================================================
        # Використовуємо SSOT reducer для гарантії правильного переходу
        # КРИТИЧНО: Override застосовується ТІЛЬКИ якщо це не глобальні приоритети
        # (COMPLAINT, PHOTO_IDENT завжди мають пріоритет)
        from src.agents.langgraph.fsm.transition_reducer import compute_transition
        
        user_text = user_message if isinstance(user_message, str) else str(user_message)
        has_image_state = state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
        
        # Глобальні приоритети - НЕ перетираємо
        global_priority_intents = {"COMPLAINT", "PHOTO_IDENT"}
        if intent in global_priority_intents:
            # Для глобальних приоритетів довіряємо LLM/reducer без override
            logger.debug(
                "[SESSION %s] Global priority intent %s - skipping SSOT override",
                session_id,
                intent,
            )
        else:
            # Викликаємо SSOT reducer
            transition = compute_transition(
                state=state,
                intent=intent or "DISCOVERY_OR_QUESTION",
                has_image=has_image_state,
                user_message=user_text,
            )
            
            # Якщо reducer визначив інший стан, ніж LLM - використовуємо рішення reducer (SSOT)
            # Але ТІЛЬКИ якщо це не глобальний приоритет
            if transition.next_state != new_state_str:
                logger.info(
                    "[SESSION %s] SSOT Override: LLM state=%s, SSOT state=%s. Using SSOT.",
                    session_id,
                    new_state_str,
                    transition.next_state,
                )
                new_state_str = transition.next_state
                response.metadata.current_state = new_state_str
                
                # Гарантуємо правильний intent для подальших переходів
                if transition.next_state == State.STATE_5_PAYMENT_DELIVERY.value:
                    if intent != "PAYMENT_DELIVERY":
                        intent = "PAYMENT_DELIVERY"
                        response.metadata.intent = "PAYMENT_DELIVERY"

        selected_products = state.get("selected_products", [])

        # CRITICAL: In STATE_5_PAYMENT_DELIVERY, prevent product duplication
        # Only allow adding products if user explicitly requests it (add keywords)
        is_payment_state = current_state == State.STATE_5_PAYMENT_DELIVERY.value

        if response.products:
            new_products = [p.model_dump() for p in response.products]
            user_text = user_message if isinstance(user_message, str) else str(user_message)
            user_text_lower = user_text.lower()
            # Use SSOT rules module instead of duplicated keywords
            from src.agents.langgraph.rules.cart_intent import detect_add_to_cart

            has_explicit_add_intent = detect_add_to_cart(user_text_lower)

            # In payment state, ONLY append if explicit add intent
            # Otherwise, ignore new products (they're likely hallucination/side-effect)
            if is_payment_state:
                if has_explicit_add_intent and selected_products:
                    # User explicitly wants to add more products
                    merged: list[dict[str, Any]] = []
                    seen: set[str] = set()
                    for item in [*selected_products, *new_products]:
                        pid = item.get("id")
                        name = str(item.get("name") or "").strip().lower()
                        size = str(item.get("size") or "").strip().lower()
                        color = str(item.get("color") or "").strip().lower()
                        key = f"{pid}:{size}:{color}" if pid else f"{name}:{size}:{color}"
                        if key in seen:
                            continue
                        seen.add(key)
                        merged.append(item)
                    selected_products = merged
                    logger.info(
                        "Agent appended products in payment state: now=%d (added=%d)",
                        len(selected_products),
                        len(new_products),
                    )
                else:
                    # In payment state without explicit add intent → ignore new products
                    logger.info(
                        "⚠️ [SESSION %s] Ignoring %d products from LLM in payment state (no explicit add intent)",
                        session_id,
                        len(new_products),
                    )
                    # Keep existing products unchanged
                    selected_products = selected_products or []
            else:
                # Not in payment state - normal logic
                should_append = bool(selected_products) and has_explicit_add_intent

            if should_append:
                merged: list[dict[str, Any]] = []
                seen: set[str] = set()
                for item in [*selected_products, *new_products]:
                    pid = item.get("id")
                    name = str(item.get("name") or "").strip().lower()
                    size = str(item.get("size") or "").strip().lower()
                    color = str(item.get("color") or "").strip().lower()
                    key = f"{pid}:{size}:{color}" if pid else f"{name}:{size}:{color}"
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(item)
                selected_products = merged
                logger.info(
                    "Agent appended products to cart: now=%d (added=%d)",
                    len(selected_products),
                    len(new_products),
                )
            else:
                selected_products = new_products
                logger.info("Agent found products: %s", [p.name for p in response.products])
        else:
            # Keep existing products if LLM didn't return new ones
            selected_products = selected_products or []

        # =====================================================================
        # CRITICAL: Extract size from user_message if missing
        # This prevents dialog loop when user says "98" but LLM doesn't
        # include size in products[]
        # =====================================================================
        fallback_used = False
        fallback_reasons = []

        if selected_products and current_state == State.STATE_3_SIZE_COLOR.value:
            first_product = selected_products[0]
            if not first_product.get("size"):
                user_text = user_message if isinstance(user_message, str) else str(user_message)

                # Try to extract height from user message (e.g., "98" -> height 98 cm)
                from .utils import extract_height_from_text

                height_cm = extract_height_from_text(user_text)
                if height_cm:
                    # Convert height to size
                    extracted_size = height_to_size(height_cm)
                    first_product["size"] = extracted_size
                    fallback_used = True
                    fallback_reasons.append("size_from_user_height")
                    logger.info(
                        "🔧 [SESSION %s] Extracted size='%s' from user height=%d cm (message: '%s')",
                        session_id,
                        extracted_size,
                        height_cm,
                        user_text[:50],
                    )

        # =====================================================================
        # FALLBACK: Extract size from LLM response if not in products
        # This prevents dead loop when LLM says "раджу 146-152" but forgets
        # to include size in products[]
        # NOTE: This is a SAFETY NET, not the primary path!
        # Primary path: LLM should return structured products[] with size
        # =====================================================================
        if selected_products and current_state == State.STATE_3_SIZE_COLOR.value:
            first_product = selected_products[0]
            if not first_product.get("size"):
                # Try to extract size from response messages
                extracted_size = extract_size_from_response(response.messages)
                if extracted_size:
                    first_product["size"] = extracted_size
                    fallback_used = True
                    fallback_reasons.append("size_from_llm_response")
                    logger.warning(
                        "⚠️ [SESSION %s] FALLBACK USED: extracted size='%s' from LLM response text. "
                        "LLM should return size in products[] field, not in message text.",
                        session_id,
                        extracted_size,
                    )
            # Also check if color is known from vision but missing
            if not first_product.get("color") and state.get("identified_color"):
                first_product["color"] = state.get("identified_color")
                fallback_used = True
                fallback_reasons.append("color_from_vision_state")
                logger.info(
                    "🔧 [SESSION %s] Fallback: copied color='%s' from vision",
                    session_id,
                    first_product["color"],
                )

        # Track fallback usage as metric (for monitoring LLM quality degradation)
        if fallback_used:
            track_metric(
                "llm_fallback_parsing_used",
                1,
                {
                    "session_id": session_id,
                    "state": current_state,
                    "reasons": ",".join(fallback_reasons),
                },
                )

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Log
        log_agent_step(
            session_id=session_id,
            state=new_state_str,
            intent=intent,
            event=response.event,
            latency_ms=latency_ms,
            extra={
                "trace_id": trace_id,
                "old_state": current_state,
                "products_count": len(selected_products),
            },
        )
        track_metric("agent_node_latency_ms", latency_ms)

        # Update customer data if extracted
        metadata_update = state.get("metadata", {}).copy()
        metadata_update["current_state"] = new_state_str
        metadata_update["intent"] = intent

        if selected_products:
            first_name = str(selected_products[0].get("name") or "").strip()
            if first_name:
                metadata_update["current_product_name"] = first_name

        # Обновляем customer_data из PaymentResponse (если был вызван payment_agent)
        if hasattr(response, 'customer_data') and response.customer_data:
            if response.customer_data.name:
                metadata_update["customer_name"] = response.customer_data.name
            if response.customer_data.phone:
                metadata_update["customer_phone"] = response.customer_data.phone
            if response.customer_data.city:
                metadata_update["customer_city"] = response.customer_data.city
            if response.customer_data.nova_poshta:
                metadata_update["customer_nova_poshta"] = response.customer_data.nova_poshta

        # =====================================================================
        # CRITICAL: Set vision_greeted if greeting was shown
        # =====================================================================
        # Перевіряємо чи показується привітання в поточній відповіді
        # або чи є привітання в історії повідомлень
        # Це запобігає повторному привітанню навіть якщо vision_greeted не було встановлено
        if not metadata_update.get("vision_greeted"):
            # Перевірка 1: чи є привітання в поточній відповіді
            greeting_in_response = False
            if response.messages:
                for msg in response.messages:
                    content = str(msg.content if hasattr(msg, "content") else msg.get("content", "")).lower()
                    if "менеджер соф" in content or ("вітаю" in content and "mirt" in content):
                        greeting_in_response = True
                        break

            # Перевірка 2: чи є привітання в історії повідомлень
            greeting_in_history = False
            messages = state.get("messages", [])
            for msg in messages:
                if isinstance(msg, dict):
                    role = msg.get("role", "")
                    content = str(msg.get("content", "")).lower()
                    if role == "assistant" and ("менеджер соф" in content or ("вітаю" in content and "mirt" in content)):
                        greeting_in_history = True
                        break

            # Якщо привітання показано або було раніше - встановлюємо vision_greeted
            if greeting_in_response or greeting_in_history:
                metadata_update["vision_greeted"] = True
                logger.info(
                    "[SESSION %s] Set vision_greeted=True (greeting_in_response=%s, greeting_in_history=%s)",
                    session_id,
                    greeting_in_response,
                    greeting_in_history,
                )

        # =====================================================
        # DIALOG PHASE (Turn-Based State Machine)
        # =====================================================
        # QUALITY: Повна логіка переходів з state_prompts
        # - Враховує intent, products, size, color
        # - Для payment враховує sub-phases
        # =====================================================
        old_dialog_phase = state.get("dialog_phase", "INIT")
        dialog_phase = _determine_dialog_phase(
            current_state=new_state_str,
            event=response.event,
            selected_products=selected_products,
            metadata=response.metadata,
            state=state,  # Передаємо state для payment sub-phase detection
        )

        # Reset policy counters if dialog phase changed
        if old_dialog_phase != dialog_phase:
            from src.agents.langgraph.nodes.helpers.policy_snippets import _reset_policy_counters
            metadata_update = state.get("metadata", {}).copy()
            metadata_update = _reset_policy_counters(metadata_update)
            logger.debug(
                "[SESSION %s] Dialog phase changed: %s -> %s, resetting policy counters",
                session_id,
                old_dialog_phase,
                dialog_phase,
            )
            # Update metadata in state (will be merged in return)
            state["metadata"] = metadata_update

        # Build assistant message (OUTPUT_CONTRACT format) **after** all overrides
        assistant_content = {
            "event": response.event,
            "messages": [m.model_dump() for m in response.messages],
            "products": [p.model_dump() for p in response.products],
            "metadata": response.metadata.model_dump(),
        }

        if response.escalation:
            assistant_content["escalation"] = response.escalation.model_dump()

        if response.reasoning:
            assistant_content["reasoning"] = response.reasoning

        # Persist structured response for downstream consumers (Telegram, ManyChat, etc.)
        agent_response_payload = response.model_dump()

        # Async Trace Logging (Success)
        await log_trace(
            session_id=session_id,
            trace_id=trace_id,
            node_name="agent_node",
            status="SUCCESS",
            state_name=new_state_str,
            prompt_key=f"state.{new_state_str}",  # Approximate key
            input_snapshot={
                "message": user_message.content
                if hasattr(user_message, "content")
                else str(user_message)
            },
            output_snapshot=assistant_content,
            latency_ms=latency_ms,
        )

        # Детальное логирование для отладки циклов
        if current_state == State.STATE_3_SIZE_COLOR.value:
            first_product = selected_products[0] if selected_products else None
            size_info = first_product.get("size") if first_product else None
            color_info = first_product.get("color") if first_product else None
            logger.info(
                "🔄 [SESSION %s] Dialog phase: %s → %s (state: %s, products=%d, size='%s', color='%s')",
                session_id,
                state.get("dialog_phase", "INIT"),
                dialog_phase,
                new_state_str,
                len(selected_products),
                size_info or "None",
                color_info or "None",
            )
        else:
            logger.info(
                "🔄 [SESSION %s] Dialog phase: %s → %s (state: %s)",
                session_id,
                state.get("dialog_phase", "INIT"),
                dialog_phase,
                new_state_str,
            )

        if settings.DEBUG_TRACE_LOGS:
            preview_text = ""
            if response.messages:
                preview_text = response.messages[0].content
            debug_log.node_exit(
                session_id=session_id,
                node_name="agent",
                goto="route_after_agent",
                new_phase=dialog_phase,
                response_preview=preview_text,
            )

        # =====================================================================
        # MISSING PRODUCT INFO EXIT CONDITION
        # =====================================================================
        # Якщо LLM встановив escalation_reason="missing_product_info", це означає
        # що клієнт запитав про товар, але інформація відсутня в інструкції
        # Тригеримо exit condition з escalation до менеджера
        escalation_reason = response.escalation.reason if response.escalation else None
        if escalation_reason == "missing_product_info":
            logger.info(
                "[SESSION %s] Missing product info detected - exiting with escalation",
                session_id,
            )
            # from src.services.observability import track_metric  <-- REMOVE
            track_metric(
                "missing_product_info_exit",
                1,
                {
                    "session_id": session_id,
                    "current_state": new_state_str,
                    "intent": intent,
                },
            )
            # Exit condition: escalation до менеджера
            return {
                "current_state": new_state_str,
                "detected_intent": intent,
                "dialog_phase": "ESCALATED",
                "messages": [
                    {
                        "role": "assistant",
                        "content": "Передаю ваш запит менеджеру для отримання детальної інформації 🤍",
                    }
                ],
                "metadata": {
                    **metadata_update,
                    "exit_condition": "missing_product_info",
                    "policy_case": "missing_info_exit",
                },
                "selected_products": selected_products,
                "should_escalate": True,
                "escalation_reason": "Відсутня інформація по товару в інструкції",
                "escalation_level": "L1",
                "step_number": state.get("step_number", 0) + 1,
                "last_error": None,
                "agent_response": {
                    "event": "escalation",
                    "messages": [
                        {
                            "type": "text",
                            "content": "Передаю ваш запит менеджеру для отримання детальної інформації 🤍",
                        }
                    ],
                    "metadata": {
                        "session_id": session_id,
                        "current_state": new_state_str,
                        "intent": intent,
                        "escalation_level": "L1",
                    },
                    "escalation": {
                        "reason": "Відсутня інформація по товару в інструкції",
                        "target": "product_info_manager",
                    },
                },
            }

        return {
            "current_state": new_state_str,
            "detected_intent": intent,
            "dialog_phase": dialog_phase,
            "messages": [{"role": "assistant", "content": str(assistant_content)}],
            "metadata": metadata_update,
            "selected_products": selected_products,
            "should_escalate": is_escalation,
            "escalation_reason": escalation_reason,
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
            "agent_response": agent_response_payload,
        }

    except Exception as e:
        logger.error("Agent node failed for session %s: %s", session_id, e)

        if settings.DEBUG_TRACE_LOGS:
            debug_log.error(
                session_id=session_id,
                error_type=type(e).__name__,
                message=str(e) or type(e).__name__,
            )

        # Async Trace Logging (Error)
        await log_trace(
            session_id=session_id,
            trace_id=trace_id,
            node_name="agent_node",
            status="ERROR",
            error_message=str(e),
            error_category="SYSTEM",
            state_name=current_state,
        )

        return {
            "last_error": str(e),
            "tool_errors": [*state.get("tool_errors", []), f"Agent error: {e}"],
            "retry_count": state.get("retry_count", 0) + 1,
            "step_number": state.get("step_number", 0) + 1,
        }


def _determine_dialog_phase(
    current_state: str,
    event: str,
    selected_products: list,
    metadata: Any,
    state: dict[str, Any] | None = None,
) -> str:
    """
    Determine dialog_phase from LLM response for Turn-Based routing.

    QUALITY IMPLEMENTATION:
    - Використовує determine_next_dialog_phase з state_prompts
    - Перевіряє sub-phases для payment
    - Враховує наявність товарів, розміру, кольору
    """
    # Escalation завжди завершує діалог
    if event == "escalation":
        return "COMPLETED"

    # Отримуємо дані для визначення фази
    has_products = bool(selected_products)

    # Перевіряємо чи є розмір і колір
    has_size = False
    has_color = False
    size_value = None
    color_value = None

    if selected_products:
        first_product = selected_products[0]
        size_value = first_product.get("size")
        color_value = first_product.get("color")
        has_size = bool(size_value)
        has_color = bool(color_value)

        # FALLBACK: Color may be embedded in product name like "Сукня Анна (червона клітинка)"
        # If color field is empty but name contains color in parentheses, treat as has_color=True
        if not has_color:
            product_name = first_product.get("name", "")
            if "(" in product_name and ")" in product_name:
                # Наявність варіанту в дужках означає що колір вже визначений
                has_color = True
                logger.debug("Color inferred from product name: %s", product_name)

    # Отримуємо intent
    intent = ""
    if hasattr(metadata, "intent"):
        intent = metadata.intent
    elif isinstance(metadata, dict):
        intent = metadata.get("intent", "")

    # Перевіряємо user_confirmed (чи клієнт сказав "беру")
    user_confirmed = event in ("simple_answer",) and intent == "PAYMENT_DELIVERY"

    # Для STATE_5 перевіряємо sub-phase
    payment_sub_phase = None
    if current_state == State.STATE_5_PAYMENT_DELIVERY.value and state:
        payment_sub_phase = get_payment_sub_phase(state)

    # Детальное логирование для отладки циклов
    session_id = state.get("session_id", "") if state else ""
    if current_state == "STATE_3_SIZE_COLOR":
        logger.info(
            "🔍 [SESSION %s] Dialog phase check: state=%s, has_products=%s, has_size=%s (size='%s'), has_color=%s (color='%s'), intent=%s",
            session_id,
            current_state,
            has_products,
            has_size,
            size_value or "None",
            has_color,
            color_value or "None",
            intent,
        )

    # Використовуємо повну логіку переходів
    next_phase = determine_next_dialog_phase(
        current_state=current_state,
        intent=intent,
        has_products=has_products,
        has_size=has_size,
        has_color=has_color,
        user_confirmed=user_confirmed,
        payment_sub_phase=payment_sub_phase,
    )

    if current_state == "STATE_3_SIZE_COLOR":
        logger.info(
            "🔍 [SESSION %s] Dialog phase transition: %s -> %s",
            session_id,
            current_state,
            next_phase,
        )

    return next_phase
