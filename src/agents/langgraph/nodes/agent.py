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
from src.core.state_machine import State, expected_state_for_phase
from src.services.observability import log_agent_step, log_trace, track_metric
from src.services.product_matcher import extract_requested_color

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
# SIZE EXTRACTION HELPER
# =============================================================================

# Common Ukrainian size patterns
_SIZE_PATTERNS = [
    r"розмір\s*(\d{2,3}[-–]\d{2,3})",  # "розмір 146-152"
    r"раджу\s*(\d{2,3}[-–]\d{2,3})",  # "раджу 146-152"
    r"підійде\s*(\d{2,3}[-–]\d{2,3})",  # "підійде 122-128"
    r"(\d{2,3}[-–]\d{2,3})\s*см",  # "146-152 см"
    r"розмір\s*(\d{2,3})",  # "розмір 140"
]


def _merge_product_fields(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge product dicts while preserving non-empty existing fields."""
    merged = dict(existing)
    for key, new_value in incoming.items():
        if key == "price":
            if isinstance(new_value, (int, float)) and new_value > 0:
                merged[key] = new_value
            elif key not in merged:
                merged[key] = new_value
            continue
        if key in {"size", "color", "photo_url", "description"}:
            if isinstance(new_value, str) and new_value.strip():
                merged[key] = new_value
            elif key not in merged:
                merged[key] = new_value
            continue
        merged[key] = new_value
    return merged


def _merge_products(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    append: bool,
) -> list[dict[str, Any]]:
    """Merge product lists, preserving details like size/color/price."""
    by_id: dict[int, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for item in existing:
        pid = item.get("id")
        name = str(item.get("name") or "").strip().lower()
        if isinstance(pid, int) and pid > 0:
            by_id[pid] = item
        if name:
            by_name[name] = item

    merged_existing = list(existing)
    merged_incoming: list[dict[str, Any]] = []
    for item in incoming:
        pid = item.get("id")
        name = str(item.get("name") or "").strip().lower()
        existing_item = None
        if isinstance(pid, int) and pid > 0:
            existing_item = by_id.get(pid)
        if existing_item is None and name:
            existing_item = by_name.get(name)
        merged_incoming.append(
            _merge_product_fields(existing_item or {}, item) if existing_item else item
        )

    if not append:
        return merged_incoming

    seen_keys: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in [*merged_existing, *merged_incoming]:
        pid = item.get("id")
        name = str(item.get("name") or "").strip().lower()
        size = str(item.get("size") or "").strip().lower()
        color = str(item.get("color") or "").strip().lower()
        key = f"{pid}:{size}:{color}" if pid else f"{name}:{size}:{color}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        result.append(item)
    return result


def _apply_height_to_products(
    products: list[dict[str, Any]],
    height_cm: int,
) -> list[dict[str, Any]]:
    """Apply size to products when height is known but size is missing."""
    from .utils import get_size_and_price_for_height

    if not products:
        return products

    size_label, _ = get_size_and_price_for_height(height_cm)
    updated = [dict(p) for p in products]
    for product in updated:
        if not product.get("size"):
            product["size"] = size_label
    return updated


def _product_match_key(item: dict[str, Any]) -> str:
    """Stable key for product matching (id preferred, else name)."""
    pid = item.get("id")
    if isinstance(pid, int) and pid > 0:
        return f"id:{pid}"
    name = str(item.get("name") or "").strip().lower()
    return f"name:{name}" if name else ""


def _extract_size_from_response(messages: list) -> str | None:
    """
    Extract size from LLM response messages.

    Fallback when LLM forgets to include size in products[].
    Looks for patterns like "раджу 146-152" or "розмір 122-128".
    """
    import re

    for msg in messages:
        content = msg.content if hasattr(msg, "content") else str(msg)

        for pattern in _SIZE_PATTERNS:
            # Use re.IGNORECASE for proper Unicode handling
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                size = match.group(1)
                # Normalize dash
                size = size.replace("–", "-")
                logger.debug("Extracted size '%s' from: %s", size, content[:50])
                return size

    return None


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
                    if option_norms and (_norm(requested) in option_norms):
                        selected_products = state.get("selected_products", []) or []
                        if selected_products:
                            first = dict(selected_products[0])
                            if not first.get("color"):
                                first["color"] = requested
                            selected_products = [first, *selected_products[1:]]
                            state = {
                                **state,
                                "selected_products": selected_products,
                                "metadata": {
                                    **state.get("metadata", {}),
                                    "selected_color": requested,
                                },
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
    from src.services.history_trimmer import trim_message_history

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
    if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        payment_sub = get_payment_sub_phase(state)
        state_prompt = get_state_prompt(current_state, payment_sub)
        logger.info(
            "💰 [SESSION %s] Payment sub-phase: %s",
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
        # Returns STRUCTURED SupportResponse (OUTPUT_CONTRACT format)
        response: SupportResponse = await run_support(
            message=user_message,
            deps=deps,
            message_history=None,
        )

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
        # LLM-FIRST APPROACH: Trust improved prompts for intent classification
        # =====================================================================
        # The STATE_5 prompts now explicitly teach LLM that "да/так/ок" in
        # payment flow = PAYMENT_DELIVERY, not THANKYOU. LLM should output
        # requisites directly when user confirms data.
        #
        # Previous keyword-override for injecting requisites is REMOVED.
        # If LLM still makes mistakes, improve the prompt, not add patches.
        # =====================================================================
        intent = response.metadata.intent
        upsell_flow_active = bool(state.get("metadata", {}).get("upsell_flow_active"))

        # Extract from OUTPUT_CONTRACT structure
        new_state_str = response.metadata.current_state
        is_escalation = response.event == "escalation"

        # =====================================================================
        # PAYMENT START OVERRIDE (STATE_4 → STATE_5)
        # =====================================================================
        # Якщо ми в STATE_4_OFFER з фазою OFFER_MADE і юзер підтверджує
        # коротким "беру/да/ок" то примусово переходимо в STATE_5_PAYMENT_DELIVERY
        # навіть якщо LLM залишив current_state=STATE_4.
        if current_state == State.STATE_4_OFFER.value and dialog_phase == "OFFER_MADE":
            user_text = user_message if isinstance(user_message, str) else str(user_message)
            user_text_lower = user_text.lower()
            confirm_words = _OFFER_CONFIRMATION_KEYWORDS
            if any(w in user_text_lower for w in confirm_words):
                # Якщо LLM ще не перевів стан у STATE_5, робимо це явно
                if new_state_str == State.STATE_4_OFFER.value:
                    new_state_str = State.STATE_5_PAYMENT_DELIVERY.value
                    response.metadata.current_state = new_state_str
                # Гарантуємо правильний intent для подальших переходів
                if intent != "PAYMENT_DELIVERY":
                    intent = "PAYMENT_DELIVERY"
                    response.metadata.intent = "PAYMENT_DELIVERY"

        selected_products = state.get("selected_products", [])
        if response.products:
            new_products = [p.model_dump() for p in response.products]
            user_text = user_message if isinstance(user_message, str) else str(user_message)
            user_text_lower = user_text.lower()
            metadata_flags = state.get("metadata", {}) or {}
            upsell_base_products = metadata_flags.get("upsell_base_products") or []
            add_keywords = (
                "ще",
                "додай",
                "добав",
                "також",
                "і ще",
                "ще один",
                "ще одну",
                "другий",
                "другу",
                "+",
            )
            should_append = bool(selected_products) and any(
                k in user_text_lower for k in add_keywords
            )
            if upsell_flow_active:
                should_append = True

            if should_append:
                base_products = selected_products
                used_upsell_base = False
                if not base_products and upsell_base_products:
                    base_products = upsell_base_products
                    used_upsell_base = True
                selected_products = _merge_products(
                    base_products,
                    new_products,
                    append=True,
                )
                if used_upsell_base:
                    new_keys = {_product_match_key(p) for p in new_products if _product_match_key(p)}
                    if new_keys:
                        selected_products = [
                            p
                            for p in selected_products
                            if _product_match_key(p) in new_keys
                        ] + [
                            p
                            for p in selected_products
                            if _product_match_key(p) not in new_keys
                        ]
                logger.info(
                    "Agent appended products to cart: now=%d (added=%d)",
                    len(selected_products),
                    len(new_products),
                )
            else:
                selected_products = _merge_products(
                    selected_products,
                    new_products,
                    append=False,
                )
                logger.info("Agent found products: %s", [p.name for p in response.products])

        # =====================================================================
        # FALLBACK: Extract size from LLM response if not in products
        # This prevents dead loop when LLM says "раджу 146-152" but forgets
        # to include size in products[]
        # =====================================================================
        if selected_products and current_state == State.STATE_3_SIZE_COLOR.value:
            first_product = selected_products[0]
            if not first_product.get("size"):
                # Try to extract size from response messages
                extracted_size = _extract_size_from_response(response.messages)
                if extracted_size:
                    first_product["size"] = extracted_size
                    logger.info(
                        "🔧 [SESSION %s] Fallback: extracted size='%s' from LLM response",
                        session_id,
                        extracted_size,
                    )
            # Also check if color is known from vision but missing
            if not first_product.get("color") and state.get("identified_color"):
                first_product["color"] = state.get("identified_color")
                logger.info(
                    "🔧 [SESSION %s] Fallback: copied color='%s' from vision",
                    session_id,
                    first_product["color"],
                )

        # Apply height from user message to avoid re-asking for size.
        from .utils import extract_height_from_text

        height_in_text = extract_height_from_text(user_message)
        height_from_context = height_in_text or state.get("metadata", {}).get("height_cm")
        if height_from_context and selected_products:
            selected_products = _apply_height_to_products(selected_products, height_from_context)

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
        if height_in_text:
            metadata_update["height_cm"] = height_in_text

        if response.customer_data:
            if response.customer_data.name:
                metadata_update["customer_name"] = response.customer_data.name
            if response.customer_data.phone:
                metadata_update["customer_phone"] = response.customer_data.phone
            if response.customer_data.city:
                metadata_update["customer_city"] = response.customer_data.city
            if response.customer_data.nova_poshta:
                metadata_update["customer_nova_poshta"] = response.customer_data.nova_poshta

        # Clear upsell flow flag once we actually added new products.
        if upsell_flow_active and response.products:
            metadata_update["upsell_flow_active"] = False

        # =====================================================
        # DIALOG PHASE (Turn-Based State Machine)
        # =====================================================
        # QUALITY: Повна логіка переходів з state_prompts
        # - Враховує intent, products, size, color
        # - Для payment враховує sub-phases
        # =====================================================
        dialog_phase = _determine_dialog_phase(
            current_state=new_state_str,
            event=response.event,
            selected_products=selected_products,
            metadata=response.metadata,
            state=state,  # Передаємо state для payment sub-phase detection
        )
        if (
            dialog_phase == "DISCOVERY"
            and new_state_str == State.STATE_2_VISION.value
            and not selected_products
        ):
            new_state_str = State.STATE_1_DISCOVERY.value
            response.metadata.current_state = new_state_str
            metadata_update["current_state"] = new_state_str
        expected_state = expected_state_for_phase(dialog_phase)
        if expected_state and new_state_str != expected_state.value:
            logger.warning(
                "FSM guard override: phase=%s expected_state=%s got=%s (session=%s)",
                dialog_phase,
                expected_state.value,
                new_state_str,
                session_id,
            )
            track_metric(
                "fsm_guard_override",
                1,
                {
                    "phase": dialog_phase,
                    "expected_state": expected_state.value,
                    "actual_state": new_state_str,
                },
            )
            new_state_str = expected_state.value
            response.metadata.current_state = new_state_str
            metadata_update["current_state"] = new_state_str

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

        return {
            "current_state": new_state_str,
            "detected_intent": intent,
            "dialog_phase": dialog_phase,
            "messages": [{"role": "assistant", "content": str(assistant_content)}],
            "metadata": metadata_update,
            "selected_products": selected_products,
            "should_escalate": is_escalation,
            "escalation_reason": response.escalation.reason if response.escalation else None,
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
    if selected_products:
        first_product = selected_products[0]
        has_size = bool(first_product.get("size"))
        has_color = bool(first_product.get("color"))

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

    # Використовуємо повну логіку переходів
    return determine_next_dialog_phase(
        current_state=current_state,
        intent=intent,
        has_products=has_products,
        has_size=has_size,
        has_color=has_color,
        user_confirmed=user_confirmed,
        payment_sub_phase=payment_sub_phase,
    )


def _get_instructions_for_intent(intent: str, state: dict[str, Any]) -> str:
    """Get context-specific instructions based on detected intent."""

    instructions = {
        "GREETING_ONLY": (
            "Привітай клієнта тепло, як MIRT_UA менеджер Софія. "
            "Запитай чим можеш допомогти. "
            "Не перевантажуй інформацією - будь лаконічною."
        ),
        "DISCOVERY_OR_QUESTION": (
            "Клієнт шукає товар або має питання. "
            "Знайди відповідні товари в EMBEDDED CATALOG. "
            "Покажи варіанти з цінами та характеристиками. "
            "Якщо потрібно - запитай уточнення (зріст, вік, колір)."
        ),
        "SIZE_HELP": (
            "Клієнт питає про розмір. "
            "Дай КОНКРЕТНУ відповідь з розмірної сітки. "
            "Якщо знаєш зріст - підбери розмір. "
            "Якщо є вибраний товар - переходь до пропозиції!"
        ),
        "COLOR_HELP": (
            "Клієнт питає про колір. "
            "Покажи доступні кольори для товару. "
            "Якщо товар є в потрібному кольорі - підтверди. "
            "Якщо немає - запропонуй альтернативи."
        ),
        "THANKYOU_SMALLTALK": (
            "Клієнт подякував або веде світську бесіду. "
            "Відповідай тепло, але коротко. "
            "Запропонуй допомогу, якщо потрібно."
        ),
    }

    # Add product context if available
    products = state.get("selected_products", [])
    if products:
        product_names = ", ".join(p.get("name", "товар") for p in products[:3])
        base = instructions.get(intent, instructions["DISCOVERY_OR_QUESTION"])
        return f"{base}\n\nУ діалозі вже є товари: {product_names}."

    return instructions.get(intent, instructions["DISCOVERY_OR_QUESTION"])
