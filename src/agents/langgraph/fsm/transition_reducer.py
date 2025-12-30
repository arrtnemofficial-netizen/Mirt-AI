"""
SSOT Transition Reducer - Единый источник правды для переходов FSM.
====================================================================

Этот модуль централизует всю логику переходов между состояниями,
вычисления dialog_phase и определения response policy (snippets).

КЛЮЧЕВАЯ ИДЕЯ:
- dialog_phase НЕ хранится как источник правды
- dialog_phase ВСЕГДА вычисляется из current_state + payment_sub_phase
- Все переходы решаются в одном месте (этот модуль)
- Response policy (snippets) определяется здесь же

ИНВАРИАНТЫ:
1. dialog_phase = derive_dialog_phase(current_state, payment_sub_phase, ...)
2. Один user turn → максимум один assistant response
3. Snippet "Підтвердження замовлення" отправляется ровно один раз (флаг в metadata)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.core.state_machine import State

logger = logging.getLogger(__name__)


@dataclass
class TransitionDecision:
    """
    Решение о переходе состояния - SSOT для всей системы.
    
    Все компоненты (edges, nodes) должны использовать это решение,
    а не вычислять переходы самостоятельно.
    """
    # Следующее состояние
    next_state: str
    
    # Payment sub-phase (только для STATE_5_PAYMENT_DELIVERY)
    payment_sub_phase: str | None
    
    # Вычисленный dialog_phase (НЕ хранится, всегда вычисляется)
    dialog_phase: str
    
    # Response policy: какой snippet отправить (если нужно)
    response_policy: ResponsePolicy
    
    # Причина перехода (для логирования)
    reason: str


@dataclass
class ResponsePolicy:
    """
    Политика ответа: что отправить пользователю.
    
    Это определяет, нужно ли отправлять snippet или использовать LLM.
    """
    # Имя snippet для отправки (если нужно)
    snippet_name: str | None = None
    
    # Флаг: уже отправляли этот snippet?
    snippet_sent_flag: str | None = None
    
    # Использовать LLM? (если snippet не нужен)
    use_llm: bool = True


def compute_transition(
    state: dict[str, Any],
    intent: str,
    has_image: bool = False,
    user_message: str | None = None,
) -> TransitionDecision:
    """
    Вычислить переход состояния на основе текущего состояния и события.
    
    SSOT АРХИТЕКТУРА:
    - next_state ВСЕГДА берётся из core.state_machine.get_next_state() (единственный SSOT)
    - payment_sub_phase вычисляется здесь (для STATE_5)
    - dialog_phase ВСЕГДА вычисляется (derived, не хранится)
    - response_policy определяется здесь (snippets + idempotency)
    
    Args:
        state: Текущее состояние (current_state, metadata, selected_products, etc.)
        intent: Обнаруженный intent из сообщения пользователя
        has_image: Есть ли изображение в сообщении
        user_message: Текст сообщения пользователя (для проверки keywords)
    
    Returns:
        TransitionDecision с next_state, payment_sub_phase, dialog_phase, response_policy
    """
    from src.core.state_machine import Intent, get_next_state
    from src.agents.langgraph.fsm.facts import compute_facts
    
    current_state_str = state.get("current_state", State.STATE_0_INIT.value)
    metadata = state.get("metadata", {}) or {}
    session_id = state.get("session_id", metadata.get("session_id", "unknown"))
    
    # SSOT: next_state ВСЕГДА из core.state_machine
    current_state = State.from_string(current_state_str)
    intent_enum = Intent.from_string(intent)
    next_state = get_next_state(current_state, intent_enum)
    next_state_str = next_state.value
    
    logger.debug(
        "[SESSION %s] SSOT Transition: %s + %s → %s (from core.state_machine)",
        session_id,
        current_state_str,
        intent,
        next_state_str,
    )
    
    # Вычисляем факты (вынесено в отдельный модуль)
    facts = compute_facts(state, intent, user_message)
    user_confirmed = facts["user_confirmed"]
    has_products = facts["has_products"]
    has_size = facts["has_size"]
    has_color = facts["has_color"]
    
    # Определяем payment_sub_phase (если мы в STATE_5 или переходим туда)
    payment_sub_phase = None
    if current_state == State.STATE_5_PAYMENT_DELIVERY:
        from src.agents.langgraph.state_prompts import get_payment_sub_phase
        try:
            payment_sub_phase = get_payment_sub_phase(state)
        except Exception as e:
            logger.warning(
                "[SESSION %s] Failed to get payment sub-phase: %s, defaulting to REQUEST_DATA",
                session_id,
                e,
            )
            payment_sub_phase = "REQUEST_DATA"
    elif current_state == State.STATE_4_OFFER and (user_confirmed or intent == "PAYMENT_DELIVERY"):
        # Переход STATE_4 → STATE_5: начинаем с REQUEST_DATA
        payment_sub_phase = "REQUEST_DATA"
    
    # Если переходим в STATE_5, обновляем payment_sub_phase
    if next_state == State.STATE_5_PAYMENT_DELIVERY and not payment_sub_phase:
        payment_sub_phase = "REQUEST_DATA"
    
    # Вычисляем dialog_phase (НЕ хранится, всегда вычисляется)
    dialog_phase = derive_dialog_phase(
        current_state=next_state_str,
        intent=intent,
        has_products=has_products,
        has_size=has_size,
        has_color=has_color,
        user_confirmed=user_confirmed,
        payment_sub_phase=payment_sub_phase,
    )
    
    # Определяем response_policy (через manifest, без хардкода)
    from src.agents.langgraph.fsm.policy import determine_response_policy
    
    response_policy = determine_response_policy(
        next_state=next_state_str,
        payment_sub_phase=payment_sub_phase,
        metadata=metadata,
        session_id=session_id,
    )
    
    # Формируем reason для логирования
    reason = _format_transition_reason(
        from_state=current_state_str,
        to_state=next_state_str,
        intent=intent,
        user_confirmed=user_confirmed,
        payment_sub_phase=payment_sub_phase,
    )
    
    logger.info(
        "[SESSION %s] FSM Transition Decision: %s → %s (sub_phase=%s, dialog_phase=%s, reason=%s)",
        session_id,
        current_state_str,
        next_state_str,
        payment_sub_phase,
        dialog_phase,
        reason,
    )
    
    # =========================================================================
    # OBSERVABILITY: Track transition metrics
    # =========================================================================
    try:
        from src.services.observability import track_metric
        
        track_metric(
            "fsm_transition_decision",
            1,
            {
                "from_state": current_state_str,
                "to_state": next_state_str,
                "payment_sub_phase": payment_sub_phase or "N/A",
                "dialog_phase": dialog_phase,
                "intent": intent,
                "reason": reason,
                "session_id": session_id,
            },
        )
        
        # Track snippet policy decision
        if response_policy.snippet_name:
            track_metric(
                "snippet_policy_decision",
                1,
                {
                    "snippet_name": response_policy.snippet_name,
                    "snippet_sent_flag": response_policy.snippet_sent_flag or "N/A",
                    "use_llm": response_policy.use_llm,
                    "already_sent": metadata.get(response_policy.snippet_sent_flag, False) if response_policy.snippet_sent_flag else False,
                    "session_id": session_id,
                },
            )
    except Exception as e:
        logger.debug("Failed to track transition metrics: %s", e)
    
    return TransitionDecision(
        next_state=next_state_str,
        payment_sub_phase=payment_sub_phase,
        dialog_phase=dialog_phase,
        response_policy=response_policy,
        reason=reason,
    )


def derive_dialog_phase(
    current_state: str,
    intent: str,
    has_products: bool,
    has_size: bool,
    has_color: bool,
    user_confirmed: bool,
    payment_sub_phase: str | None = None,
) -> str:
    """
    Вычислить dialog_phase на основе состояния.
    
    КРИТИЧНО: dialog_phase НЕ хранится как источник правды.
    Он ВСЕГДА вычисляется из current_state + payment_sub_phase + других фактов.
    
    Это гарантирует отсутствие конфликтов между хранимым dialog_phase
    и реальным состоянием системы.
    """
    # Используем существующую логику из state_prompts.py
    from src.agents.langgraph.state_prompts import determine_next_dialog_phase
    
    return determine_next_dialog_phase(
        current_state=current_state,
        intent=intent,
        has_products=has_products,
        has_size=has_size,
        has_color=has_color,
        user_confirmed=user_confirmed,
        payment_sub_phase=payment_sub_phase,
    )


# УДАЛЕНО: _detect_user_confirmation перенесена в fsm/facts.py
# УДАЛЕНО: _determine_next_state удалена - используем core.state_machine.get_next_state() как SSOT
# УДАЛЕНО: _determine_response_policy перенесена в fsm/policy.py (использует manifest.json)


def _format_transition_reason(
    from_state: str,
    to_state: str,
    intent: str,
    user_confirmed: bool,
    payment_sub_phase: str | None,
) -> str:
    """Форматировать причину перехода для логирования."""
    parts = []
    
    if from_state != to_state:
        parts.append(f"state_change:{from_state}→{to_state}")
    
    if intent:
        parts.append(f"intent:{intent}")
    
    if user_confirmed:
        parts.append("user_confirmed")
    
    if payment_sub_phase:
        parts.append(f"payment_sub_phase:{payment_sub_phase}")
    
    return "|".join(parts) if parts else "no_change"

