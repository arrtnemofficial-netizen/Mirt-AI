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
from typing import TYPE_CHECKING, Any

# PydanticAI imports
from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.support_agent import run_support
from src.core.state_machine import State
from src.services.observability import log_agent_step, log_trace, track_metric

# State prompts and transition logic
from ..state_prompts import (
    detect_simple_intent,
    determine_next_dialog_phase,
    get_payment_sub_phase,
    get_state_prompt,
)


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents.pydantic.models import SupportResponse


logger = logging.getLogger(__name__)


# =============================================================================
# SIZE EXTRACTION HELPER
# =============================================================================

# Common Ukrainian size patterns
_SIZE_PATTERNS = [
    r"розмір\s*(\d{2,3}[-–]\d{2,3})",  # "розмір 146-152"
    r"раджу\s*(\d{2,3}[-–]\d{2,3})",   # "раджу 146-152"
    r"підійде\s*(\d{2,3}[-–]\d{2,3})", # "підійде 122-128"
    r"(\d{2,3}[-–]\d{2,3})\s*см",      # "146-152 см"
    r"розмір\s*(\d{2,3})",              # "розмір 140"
]


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

    # Create deps from state (proper DI!)
    deps = create_deps_from_state(state)

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
            "Agent response for session %s: event=%s, state=%s->%s, intent=%s, "
            "products=%d, msg=%s",
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
        # INTENT OVERRIDE: Fix LLM mistakes in STATE_5 (Payment flow)
        # =====================================================================
        # Problem: LLM interprets "да/так/ок" as THANKYOU_SMALLTALK (end of dialog)
        # Reality: In STATE_5, "да" = confirmation of delivery data, NOT goodbye
        # Solution: Override intent AND inject payment requisites
        # =====================================================================
        intent = response.metadata.intent
        _confirmed_data_this_turn = False  # Track if we override to show requisites
        
        if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
            confirmation_words = ["да", "так", "yes", "ок", "добре", "згодна", "правильно", "вірно", "все вірно", "підтверджую"]
            user_text = user_message.lower() if isinstance(user_message, str) else str(user_message).lower()

            # Determine payment sub-phase from previous state (before this turn)
            payment_sub = get_payment_sub_phase(state)

            # In CONFIRM_DATA sub-phase, short confirmations like "да/так/ок" mean
            # the client has approved delivery details and we must immediately
            # show payment requisites, regardless of how the LLM labeled intent.
            if payment_sub == "CONFIRM_DATA":
                for word in confirmation_words:
                    if word in user_text:
                        # Override to PAYMENT_DELIVERY - continue payment flow
                        intent = "PAYMENT_DELIVERY"
                        response.metadata.intent = "PAYMENT_DELIVERY"
                        # Don't close dialog! Stay in STATE_5
                        response.metadata.current_state = State.STATE_5_PAYMENT_DELIVERY.value
                        response.event = "simple_answer"
                        _confirmed_data_this_turn = True
                        
                        # CRITICAL: Inject payment requisites into response!
                        # LLM didn't do it, so we do it manually
                        from src.agents.pydantic.models import MessageBubble
                        response.messages = [
                            MessageBubble(type="text", content="Чудово, дані зафіксовано! 🤍"),
                            MessageBubble(type="text", content="Ловіть реквізити для оплати:"),
                            MessageBubble(type="text", content="ФОП Кутний Михайло Михайлович\nIBAN: UA653220010000026003340139893\nІПН/ЄДРПОУ: 3278315599\nПризначення: ОПЛАТА ЗА ТОВАР"),
                            MessageBubble(type="text", content="Надішліть, будь ласка, скрін оплати 🌸"),
                        ]
                        
                        logger.info(
                            "🔄 [SESSION %s] CONFIRM_DATA→SHOW_PAYMENT: injected requisites after confirmation",
                            session_id,
                        )
                        break

        # Extract from OUTPUT_CONTRACT structure
        new_state_str = response.metadata.current_state
        is_escalation = response.event == "escalation"

        # Extract products (already typed from CATALOG!)
        selected_products = state.get("selected_products", [])
        if response.products:
            selected_products = [p.model_dump() for p in response.products]
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

        # Build assistant message (OUTPUT_CONTRACT format)
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

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Log
        log_agent_step(
            session_id=session_id,
            state=new_state_str,
            intent=intent,
            event=response.event,
            latency_ms=latency_ms,
            extra={
                "old_state": current_state,
                "products_count": len(selected_products),
            },
        )
        track_metric("agent_node_latency_ms", latency_ms)

        # Update customer data if extracted
        metadata_update = state.get("metadata", {}).copy()
        metadata_update["current_state"] = new_state_str
        metadata_update["intent"] = intent

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

        if response.customer_data:
            if response.customer_data.name:
                metadata_update["customer_name"] = response.customer_data.name
            if response.customer_data.phone:
                metadata_update["customer_phone"] = response.customer_data.phone
            if response.customer_data.city:
                metadata_update["customer_city"] = response.customer_data.city
            if response.customer_data.nova_poshta:
                metadata_update["customer_nova_poshta"] = response.customer_data.nova_poshta

        # =====================================================================
        # PAYMENT FLOW STATE MACHINE (Quality Implementation)
        # =====================================================================
        # Sub-phases:
        #   1. COLLECT_DATA: ПІБ, телефон, місто, НП
        #   2. CHOOSE_PAYMENT: повна оплата / передплата
        #   3. SHOW_REQUISITES: реквізити ФОП
        #   4. WAIT_SCREENSHOT: чекаємо скрін
        #   5. COMPLETE: замовлення прийнято
        # =====================================================================
        if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
            from src.agents.pydantic.models import MessageBubble
            
            user_text = user_message if isinstance(user_message, str) else str(user_message)
            user_text_lower = user_text.lower()
            
            # Get current sub-phase
            payment_sub_phase = metadata_update.get("payment_sub_phase", "COLLECT_DATA")
            
            # Check what data we already have
            has_name = bool(metadata_update.get("customer_name"))
            has_phone = bool(metadata_update.get("customer_phone"))
            has_city = bool(metadata_update.get("customer_city"))
            has_np = bool(metadata_update.get("customer_nova_poshta"))
            has_all_data = has_name and has_phone and has_city and has_np
            
            # Parse ONLY phone and NP from message (regex-reliable)
            # Names and cities are handled by LLM with proper prompting
            from src.services.client_data_parser_minimal import parse_minimal
            parsed = parse_minimal(user_text)
            
            if parsed.phone and not has_phone:
                metadata_update["customer_phone"] = parsed.phone
                logger.info("📝 [SESSION %s] Parsed phone: %s", session_id, parsed.phone)
            if parsed.nova_poshta and not has_np:
                metadata_update["customer_nova_poshta"] = parsed.nova_poshta
                logger.info("📝 [SESSION %s] Parsed NP: %s", session_id, parsed.nova_poshta)
            
            # Re-check after parsing
            has_all_data = all([
                metadata_update.get("customer_name"),
                metadata_update.get("customer_phone"),
                metadata_update.get("customer_city"),
                metadata_update.get("customer_nova_poshta"),
            ])
            
            # =========== SUB-PHASE LOGIC ===========
            
            # PHASE 1→2: Got all data, ask about payment method
            if payment_sub_phase == "COLLECT_DATA" and has_all_data:
                name = metadata_update["customer_name"]
                phone = metadata_update["customer_phone"]
                city = metadata_update["customer_city"]
                np_num = metadata_update["customer_nova_poshta"]
                
                response.messages = [
                    MessageBubble(type="text", content=f"Записала дані 📝"),
                    MessageBubble(type="text", content=f"Отримувач: {name}"),
                    MessageBubble(type="text", content=f"Телефон: {phone}"),
                    MessageBubble(type="text", content=f"Доставка: {city}, НП {np_num}"),
                    MessageBubble(type="text", content="Як зручніше оплатити?\n✅ Повна оплата на ФОП (без комісій)\n✅ Передплата 200 грн (решта на НП)"),
                ]
                metadata_update["payment_sub_phase"] = "CHOOSE_PAYMENT"
                response.event = "simple_answer"
                new_state_str = State.STATE_5_PAYMENT_DELIVERY.value
                logger.info("💰 [SESSION %s] Payment sub-phase: COLLECT_DATA → CHOOSE_PAYMENT", session_id)
            
            # PHASE 2→3: User chose payment method, show requisites
            elif payment_sub_phase == "CHOOSE_PAYMENT":
                # Detect payment method choice
                full_payment_keywords = ["повна", "повну", "повної", "повністю", "на фоп", "фоп", "без комісії"]
                prepay_keywords = ["передплат", "200", "частин", "залишок", "нп", "накладен"]
                
                is_full = any(kw in user_text_lower for kw in full_payment_keywords)
                is_prepay = any(kw in user_text_lower for kw in prepay_keywords)
                
                # Get price from state (selected products)
                price = 0
                products = state.get("selected_products", [])
                if products:
                    price = products[0].get("price", 0)
                if not price:
                    price = 2180  # Default if unknown
                
                if is_full or is_prepay:
                    payment_amount = price if is_full else 200
                    metadata_update["payment_method"] = "full" if is_full else "prepay"
                    metadata_update["payment_amount"] = payment_amount
                    
                    response.messages = [
                        MessageBubble(type="text", content=f"Супер! Сума до сплати: {payment_amount} грн 💳"),
                        MessageBubble(type="text", content="Реквізити для оплати:"),
                        MessageBubble(type="text", content="ФОП Кутний Михайло Михайлович\nІБАН: UA653220010000026003340139893\nІПН: 3278315599\nПризначення: оплата за товар"),
                        MessageBubble(type="text", content="Після оплати надішліть скрін квитанції 🌸"),
                    ]
                    metadata_update["payment_sub_phase"] = "WAIT_SCREENSHOT"
                    response.event = "simple_answer"
                    new_state_str = State.STATE_5_PAYMENT_DELIVERY.value
                    logger.info("💰 [SESSION %s] Payment sub-phase: CHOOSE_PAYMENT → WAIT_SCREENSHOT (method=%s)", 
                               session_id, metadata_update["payment_method"])
                else:
                    # User said something else, clarify
                    response.messages = [
                        MessageBubble(type="text", content="Підкажіть, як зручніше оплатити - повна оплата чи передплата 200 грн? 🤍"),
                    ]
                    response.event = "simple_answer"
            
            # PHASE 3→4: User sent screenshot or confirmed payment
            elif payment_sub_phase == "WAIT_SCREENSHOT":
                # Detect payment confirmation
                confirm_keywords = ["оплатил", "оплатила", "сплатил", "сплатила", "відправив", "відправила", 
                                   "переказал", "переказала", "надіслав", "надіслала", "скрін", "готово", "done"]
                is_confirmed = any(kw in user_text_lower for kw in confirm_keywords)
                
                # Also check if image was sent (screenshot)
                has_image_now = state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
                
                if is_confirmed or has_image_now:
                    response.messages = [
                        MessageBubble(type="text", content="Дякую за оплату! 🎉"),
                        MessageBubble(type="text", content="Замовлення прийнято. Передаю менеджеру для формування відправки."),
                        MessageBubble(type="text", content="Як буде трек-номер — напишемо вам 🤍"),
                    ]
                    metadata_update["payment_sub_phase"] = "COMPLETE"
                    metadata_update["payment_confirmed"] = True
                    response.event = "escalation"
                    new_state_str = State.STATE_7_END.value
                    logger.info("💰 [SESSION %s] Payment sub-phase: WAIT_SCREENSHOT → COMPLETE", session_id)
                else:
                    # Remind about payment
                    response.messages = [
                        MessageBubble(type="text", content="Чекаю скрін оплати 🌸"),
                    ]
                    response.event = "simple_answer"

        # Mark data as confirmed if we injected requisites this turn
        if _confirmed_data_this_turn:
            metadata_update["delivery_data_confirmed"] = True
            logger.info("🔄 [SESSION %s] Set delivery_data_confirmed=True", session_id)

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

        logger.info(
            "🔄 [SESSION %s] Dialog phase: %s → %s (state: %s)",
            session_id,
            state.get("dialog_phase", "INIT"),
            dialog_phase,
            new_state_str,
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
            "Привітай клієнта тепло, як MIRT_UA менеджер Ольга. "
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
