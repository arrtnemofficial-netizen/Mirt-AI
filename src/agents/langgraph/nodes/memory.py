"""
Memory Nodes - AGI-Style Memory Layer (Titans-like).
=====================================================
Два nodes для інтеграції памʼяті в LangGraph:

1. memory_context_node - завантажує profile + facts ПЕРЕД агентами
   - Не блокує UX (швидкий read з Supabase)
   - Додає контекст в state для AgentDeps

2. memory_update_node - тихо оновлює памʼять ПІСЛЯ ключових стейтів
   - Запускає MemoryAgent для класифікації фактів
   - Застосовує gating (importance >= 0.6, surprise >= 0.4)
   - Не впливає на відповідь користувачу

Де в графі живе памʼять:
- memory_context_node → ДО agent/vision/offer (пре-контекст)
- memory_update_node → ПІСЛЯ offer/payment/complaint (пост-контекст)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.agents.langgraph.routers.base import to_schema
from src.agents.pydantic.memory_agent import analyze_for_memory, extract_quick_facts
from src.agents.pydantic.memory_models import NewFact
from src.core.state_machine import State
from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service
from src.services.memory import MemoryService
from src.services.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


# =============================================================================
# MEMORY CONTEXT NODE (Pre-agent)
# =============================================================================


async def memory_context_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Завантажити контекст памʼяті перед агентами.

    Цей node:
    1. Завантажує UserProfile (Persistent Memory)
    2. Завантажує top-K Facts (Fluid Memory)
    3. Генерує форматований контекст для промпта
    4. Зберігає все в state для AgentDeps

    Args:
        state: Current LangGraph state

    Returns:
        State update with memory context
    """
    schema_state = to_schema(state)
    start_time = time.perf_counter()
    session_id = schema_state.session_id
    user_id = schema_state.metadata.get("user_id", "")
    trace_id = schema_state.trace_id
    current_state = schema_state.current_state

    log_agent_step(
        session_id=session_id,
        state=current_state or "UNKNOWN",
        intent="memory",
        event="memory_context.start",
        extra={"trace_id": trace_id, "user_id": user_id},
    )

    # Skip if no user_id
    if not user_id:
        logger.debug("[SESSION %s] No user_id, skipping memory context", session_id)
        return {"step_number": schema_state.step_number + 1}

    try:
        memory_service = MemoryService()

        if not memory_service.enabled:
            logger.debug("[SESSION %s] Memory service disabled", session_id)
            return {"step_number": schema_state.step_number + 1}

        # Load memory context
        context = await memory_service.load_memory_context(user_id)

        # Generate prompt block
        memory_prompt = context.to_prompt_block() if not context.is_empty() else None

        elapsed = (time.perf_counter() - start_time) * 1000

        logger.info(
            "📚 [SESSION %s] Memory context loaded: profile=%s, facts=%d, %.1fms",
            session_id,
            "yes" if context.profile else "no",
            len(context.facts),
            elapsed,
        )

        track_metric("memory_context_load_ms", elapsed)

        log_agent_step(
            session_id=session_id,
            state=current_state or "UNKNOWN",
            intent="memory",
            event="memory_context.complete",
            extra={
                "trace_id": trace_id,
                "has_profile": context.profile is not None,
                "facts_count": len(context.facts),
                "elapsed_ms": elapsed,
            },
        )

        # =================================================================
        # SITNIKS FIRST TOUCH (on first message only)
        # =================================================================
        sitniks_result = None
        step_number = schema_state.step_number

        if step_number <= 1:
            metadata = schema_state.metadata
            instagram_username = metadata.get("instagram_username")
            telegram_username = metadata.get("user_nickname")

            if instagram_username or telegram_username:
                try:
                    sitniks_service = get_sitniks_chat_service()
                    if sitniks_service.enabled:
                        sitniks_result = await sitniks_service.handle_first_touch(
                            user_id=session_id,
                            instagram_username=instagram_username,
                            telegram_username=telegram_username,
                        )
                        logger.info(
                            "[SESSION %s] Sitniks first touch: %s",
                            session_id,
                            sitniks_result,
                        )
                except Exception as e:
                    logger.warning("[SESSION %s] Sitniks first touch error: %s", session_id, e)

        # Return state update with memory context
        return {
            "step_number": step_number + 1,
            "memory_profile": context.profile,
            "memory_facts": context.facts,
            "memory_context_prompt": memory_prompt,
            "sitniks_chat_id": sitniks_result.get("chat_id") if sitniks_result else None,
            "sitniks_first_touch_done": sitniks_result.get("success") if sitniks_result else False,
        }

    except Exception as e:
        logger.error("[SESSION %s] Memory context error: %s", session_id, e)
        track_metric("memory_context_error", 1)

        # Don't fail the graph - just return empty memory
        return {"step_number": schema_state.step_number + 1}


# =============================================================================
# MEMORY UPDATE NODE (Post-agent)
# =============================================================================

# Phases that trigger memory update
# IMPORTANT: Trigger on EVERY phase to capture facts early!
MEMORY_TRIGGER_PHASES = {
    "INIT",  # STATE_0: Новий діалог
    "DISCOVERY",  # STATE_1: Збір контексту
    "VISION_DONE",  # STATE_2: Vision впізнав товар
    "WAITING_FOR_SIZE",  # STATE_3: Потрібен розмір
    "WAITING_FOR_COLOR",  # STATE_3: Потрібен колір
    "SIZE_COLOR_DONE",  # STATE_3→4: Готові до offer
    "OFFER_MADE",  # STATE_4: Пропозиція зроблена
    "WAITING_FOR_DELIVERY_DATA",  # STATE_5: Чекаємо дані доставки
    "WAITING_FOR_PAYMENT_PROOF",  # STATE_5: Payment flow
    "COMPLETED",  # STATE_7: Діалог завершено
    "COMPLAINT",  # STATE_8: Скарга
}

# States that trigger memory update
MEMORY_TRIGGER_STATES = {
    State.STATE_0_INIT,
    State.STATE_1_DISCOVERY,
    State.STATE_2_VISION,
    State.STATE_3_SIZE_COLOR,
    State.STATE_4_OFFER,
    State.STATE_5_PAYMENT_DELIVERY,
    State.STATE_7_END,
    State.STATE_8_COMPLAINT,
}


async def memory_update_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Тихе оновлення памʼяті після ключових стейтів.

    Цей node:
    1. Перевіряє чи потрібне оновлення (trigger phases)
    2. Запускає MemoryAgent для класифікації фактів
    3. Застосовує gating (importance >= 0.6, surprise >= 0.4)
    4. Зберігає нові факти / оновлює існуючі

    ВАЖЛИВО: Не впливає на відповідь користувачу!
    Latency цього node не блокує UX.

    Args:
        state: Current LangGraph state

    Returns:
        State update (minimal, just step_number)
    """
    schema_state = to_schema(state)
    start_time = time.perf_counter()
    session_id = schema_state.session_id
    user_id = schema_state.metadata.get("user_id", "")
    dialog_phase = schema_state.dialog_phase
    current_state = schema_state.current_state
    trace_id = schema_state.trace_id

    log_agent_step(
        session_id=session_id,
        state=current_state or "UNKNOWN",
        intent="memory",
        event="memory_update.start",
        extra={
            "trace_id": trace_id,
            "user_id": user_id,
            "phase": dialog_phase,
        },
    )

    # Skip if no user_id
    if not user_id:
        return {"step_number": schema_state.step_number + 1}

    # Check if we should trigger memory update
    should_trigger = dialog_phase in MEMORY_TRIGGER_PHASES or current_state in MEMORY_TRIGGER_STATES

    if not should_trigger:
        logger.debug(
            "[SESSION %s] Skipping memory update (phase=%s, state=%s)",
            session_id,
            dialog_phase,
            current_state,
        )
        return {"step_number": schema_state.step_number + 1}

    try:
        memory_service = MemoryService()

        if not memory_service.enabled:
            return {"step_number": schema_state.step_number + 1}

        # Get messages for analysis
        messages = schema_state.messages
        if not messages:
            return {"step_number": schema_state.step_number + 1}

        # Convert messages to dict format if needed
        message_dicts = []
        for msg in messages[-10:]:  # Last 10 messages
            if isinstance(msg, dict):
                message_dicts.append(msg)
            elif hasattr(msg, "content") and hasattr(msg, "type"):
                message_dicts.append(
                    {
                        "role": getattr(msg, "type", "unknown"),
                        "content": getattr(msg, "content", ""),
                    }
                )

        # =====================================================================
        # OPTION 1: Quick facts extraction (no LLM, fast)
        # =====================================================================
        # Для швидкого витягу очевидних фактів (зріст, вік, місто)
        user_messages = [m for m in message_dicts if m.get("role") == "user"]
        quick_facts = []
        for msg in user_messages[-3:]:  # Last 3 user messages
            content = msg.get("content", "")
            quick_facts.extend(extract_quick_facts(content))

        # Store quick facts with high importance (bypass gating for obvious facts)
        quick_stored = 0
        for qf in quick_facts:
            new_fact = NewFact(
                content=qf["content"],
                fact_type=qf["fact_type"],
                category=qf["category"],
                importance=0.9,  # High importance for extracted facts
                surprise=0.7,  # Medium-high surprise
                ttl_days=None,  # No expiry
            )
            result = await memory_service.store_fact(
                user_id, new_fact, session_id, bypass_gating=True
            )
            if result:
                quick_stored += 1

                # Also update profile if applicable
                if "field" in qf:
                    field = qf["field"]
                    value = qf["extracted_value"]
                    if field in ["height_cm", "age", "gender", "name"]:
                        await memory_service.update_profile(user_id, child_profile={field: value})
                    elif field == "city":
                        await memory_service.update_profile(user_id, logistics={"city": value})

        # =====================================================================
        # OPTION 2: Full LLM analysis (for complex facts)
        # =====================================================================
        # Тільки якщо є достатньо повідомлень і це важливий стейт
        llm_analysis_threshold = 5  # Min messages for LLM analysis

        if len(message_dicts) >= llm_analysis_threshold and current_state in MEMORY_TRIGGER_STATES:
            # Load existing facts and profile for context
            existing_facts = schema_state.memory_facts
            profile = schema_state.memory_profile

            # Run MemoryAgent
            decision = await analyze_for_memory(
                messages=message_dicts,
                user_id=user_id,
                session_id=session_id,
                profile=profile,
                existing_facts=existing_facts,
            )

            # Apply decision (with gating)
            stats = await memory_service.apply_decision(user_id, decision, session_id)

            elapsed = (time.perf_counter() - start_time) * 1000

            logger.info(
                "🧠 [SESSION %s] Memory update: quick=%d, stored=%d, updated=%d, rejected=%d, %.1fms",
                session_id,
                quick_stored,
                stats.get("stored", 0),
                stats.get("updated", 0),
                stats.get("rejected", 0),
                elapsed,
            )

            track_metric("memory_update_ms", elapsed)
            track_metric("memory_facts_stored", stats.get("stored", 0) + quick_stored)

        else:
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.info(
                "🧠 [SESSION %s] Quick memory update: stored=%d, %.1fms",
                session_id,
                quick_stored,
                elapsed,
            )

        log_agent_step(
            session_id=session_id,
            state=current_state or "UNKNOWN",
            intent="memory",
            event="memory_update.complete",
            extra={"trace_id": trace_id, "elapsed_ms": elapsed},
        )

        return {"step_number": schema_state.step_number + 1}

    except Exception as e:
        logger.error("[SESSION %s] Memory update error: %s", session_id, e)
        track_metric("memory_update_error", 1)

        # Don't fail the graph
        return {"step_number": schema_state.step_number + 1}


# =============================================================================
# CONDITIONAL HELPER
# =============================================================================


def should_load_memory(state: dict[str, Any]) -> bool:
    """
    Визначити чи потрібно завантажувати памʼять.

    Returns True якщо:
    - Є user_id
    - Це не перше повідомлення (є хоч якась історія)
    - Не в escalation
    """
    schema_state = to_schema(state)
    user_id = schema_state.metadata.get("user_id", "")
    if not user_id:
        return False

    dialog_phase = schema_state.dialog_phase
    return dialog_phase not in {"COMPLAINT", "OUT_OF_DOMAIN"}


def should_update_memory(state: dict[str, Any]) -> bool:
    """
    Визначити чи потрібно оновлювати памʼять.

    Returns True якщо:
    - Є user_id
    - Знаходимось в trigger phase/state
    """
    schema_state = to_schema(state)
    user_id = schema_state.metadata.get("user_id", "")
    if not user_id:
        return False

    dialog_phase = schema_state.dialog_phase
    current_state = schema_state.current_state

    return dialog_phase in MEMORY_TRIGGER_PHASES or current_state in MEMORY_TRIGGER_STATES
