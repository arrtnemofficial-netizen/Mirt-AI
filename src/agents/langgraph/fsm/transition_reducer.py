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
import re
from dataclasses import dataclass
from typing import Any

from src.core.state_machine import State

logger = logging.getLogger(__name__)

_STATE5_SHORT_ACKS = {
    "так",
    "да",
    "ok",
    "okay",
    "ок",
    "окей",
    "добре",
    "дякую",
    "спасибі",
}

_STATE5_EXPLICIT_CANCEL_MARKERS = {
    "скасувати",
    "відміна",
    "відмов",
    "не хочу",
    "не треба",
    "передум",
    "cancel",
    "stop",
}


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

    # Есть ли deferred intents для следующего шага
    has_deferred_intents: bool = False


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
    deferred_intents: list[str] | None = None,
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
    from src.conf.config import settings
    
    current_state_str = state.get("current_state", State.STATE_0_INIT.value)
    metadata = state.get("metadata", {}) or {}
    session_id = state.get("session_id", metadata.get("session_id", "unknown"))
    
    # SSOT: next_state ВСЕГДА из core.state_machine
    current_state = State.from_string(current_state_str)
    
    # Вычисляем факты ПЕРЕД определением next_state (нужно для user_confirmed)
    facts = compute_facts(state, intent, user_message)
    user_confirmed = facts["user_confirmed"]
    payment_proof_received = facts.get("payment_proof_received", False)
    strict_state5_override = False

    if (
        settings.FSM_STATE5_STRICT_MODE
        and current_state == State.STATE_5_PAYMENT_DELIVERY
        and intent == "THANKYOU_SMALLTALK"
        and not payment_proof_received
        and _is_state5_short_ack_not_cancel(user_message)
    ):
        logger.info(
            "[SESSION %s] STATE_5 strict mode: short acknowledgement '%s' treated as PAYMENT_DELIVERY",
            session_id,
            (user_message or "").strip()[:50],
        )
        intent = "PAYMENT_DELIVERY"
        strict_state5_override = True
    
    # КРИТИЧНО: Если user_confirmed=True в STATE_4_OFFER, принудительно используем PAYMENT_DELIVERY intent
    # Это гарантирует переход STATE_4 → STATE_5 даже если intent был SIZE_HELP или другой
    if current_state == State.STATE_4_OFFER and user_confirmed:
        logger.info(
            "[SESSION %s] 🎯 User confirmed in STATE_4_OFFER: overriding intent from '%s' to PAYMENT_DELIVERY",
            session_id,
            intent,
        )
        intent_enum = Intent.PAYMENT_DELIVERY
    else:
        intent_enum = Intent.from_string(intent)
    
    next_state = get_next_state(current_state, intent_enum)
    next_state_str = next_state.value
    
    logger.debug(
        "[SESSION %s] SSOT Transition: %s + %s → %s (from core.state_machine, user_confirmed=%s)",
        session_id,
        current_state_str,
        intent_enum.value,
        next_state_str,
        user_confirmed,
    )
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
    
    has_deferred_intents = bool(deferred_intents)

    # Формируем reason для логирования
    reason = _format_transition_reason(
        from_state=current_state_str,
        to_state=next_state_str,
        intent=intent,
        user_confirmed=user_confirmed,
        payment_sub_phase=payment_sub_phase,
        strict_state5_override=strict_state5_override,
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
            already_sent = metadata.get(response_policy.snippet_sent_flag, False) if response_policy.snippet_sent_flag else False
            logger.info(
                "[SESSION %s] 🎯 Response Policy Decision: snippet='%s', flag=%s, use_llm=%s, already_sent=%s",
                session_id,
                response_policy.snippet_name,
                response_policy.snippet_sent_flag or "N/A",
                response_policy.use_llm,
                already_sent,
            )
            track_metric(
                "snippet_policy_decision",
                1,
                {
                    "snippet_name": response_policy.snippet_name,
                    "snippet_sent_flag": response_policy.snippet_sent_flag or "N/A",
                    "use_llm": response_policy.use_llm,
                    "already_sent": already_sent,
                    "session_id": session_id,
                },
            )
        else:
            logger.info(
                "[SESSION %s] 🎯 Response Policy Decision: NO snippet, use_llm=True (next_state=%s)",
                session_id,
                next_state_str,
            )
    except Exception as e:
        logger.debug("Failed to track transition metrics: %s", e)
    
    return TransitionDecision(
        next_state=next_state_str,
        payment_sub_phase=payment_sub_phase,
        dialog_phase=dialog_phase,
        response_policy=response_policy,
        reason=reason,
        has_deferred_intents=has_deferred_intents,
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
    # STATE_0_INIT transitions
    if current_state == State.STATE_0_INIT.value:
        if intent in {"GREETING_ONLY", "DISCOVERY_OR_QUESTION"}:
            return "DISCOVERY"
        elif intent == "PHOTO_IDENT":
            return "VISION_DONE"
        elif intent in ("SIZE_HELP", "COLOR_HELP"):
            return "WAITING_FOR_SIZE"
        elif intent == "PAYMENT_DELIVERY":
            return "WAITING_FOR_DELIVERY_DATA"
        elif intent == "COMPLAINT":
            return "COMPLAINT"
        elif intent == "THANKYOU_SMALLTALK":
            return "COMPLETED"
        elif intent == "OUT_OF_DOMAIN":
            return "OUT_OF_DOMAIN"
        else:
            return "DISCOVERY"

    # STATE_1_DISCOVERY transitions
    if current_state == State.STATE_1_DISCOVERY.value:
        if has_products and has_size:
            return "SIZE_COLOR_DONE"
        elif has_products:
            return "WAITING_FOR_SIZE"
        # FIXED: Handle intent-based transitions to avoid dead loops
        elif intent == "PAYMENT_DELIVERY" and user_confirmed:
            return "WAITING_FOR_DELIVERY_DATA"
        elif intent == "COMPLAINT":
            return "COMPLAINT"
        elif intent == "THANKYOU_SMALLTALK":
            return "COMPLETED"
        else:
            return "DISCOVERY"  # Stay in discovery until we have products

    # STATE_2_VISION transitions
    if current_state == State.STATE_2_VISION.value:
        if has_products:
            return "WAITING_FOR_SIZE"
        # FIXED: If vision didn't find product, go to DISCOVERY for clarification
        # instead of staying in VISION_DONE which causes dead loop
        else:
            return "DISCOVERY"  # Let agent ask clarifying questions

    # STATE_3_SIZE_COLOR transitions
    if current_state == State.STATE_3_SIZE_COLOR.value:
        if has_products and has_size and has_color:
            return "SIZE_COLOR_DONE"
        elif has_size:
            return "WAITING_FOR_COLOR"
        else:
            return "WAITING_FOR_SIZE"

    # STATE_4_OFFER transitions
    if current_state == State.STATE_4_OFFER.value:
        if user_confirmed or intent == "PAYMENT_DELIVERY":
            return "WAITING_FOR_DELIVERY_DATA"
        else:
            return "OFFER_MADE"

    # STATE_5_PAYMENT_DELIVERY transitions
    if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        # CRITICAL: Map sub-phase to dialog_phase deterministically
        # SHOW_PAYMENT means we showed payment details and are waiting for proof (screenshot)
        # CONFIRM_DATA means we're confirming delivery data before showing payment
        phase_map = {
            "THANK_YOU": "UPSELL_OFFERED",
            "SHOW_PAYMENT": "WAITING_FOR_PAYMENT_PROOF",  # Waiting for screenshot/proof
            "CONFIRM_DATA": "WAITING_FOR_PAYMENT_METHOD",  # Confirming data, then show payment
            "REQUEST_DATA": "WAITING_FOR_DELIVERY_DATA",  # Still collecting delivery data
        }
        mapped_phase = phase_map.get(payment_sub_phase, "WAITING_FOR_DELIVERY_DATA")

        # Additional check: if user says "оплатила" but sub-phase wasn't updated yet,
        # force WAITING_FOR_PAYMENT_PROOF
        # (This is a safety net - ideally get_payment_sub_phase should catch this)
        if payment_sub_phase == "SHOW_PAYMENT":
            return "WAITING_FOR_PAYMENT_PROOF"

        return mapped_phase

    # STATE_6_UPSELL transitions
    if current_state == State.STATE_6_UPSELL.value:
        return "COMPLETED"

    # STATE_7_END
    if current_state == State.STATE_7_END.value:
        return "COMPLETED"

    # STATE_8_COMPLAINT
    if current_state == State.STATE_8_COMPLAINT.value:
        return "COMPLETED"

    # STATE_9_OOD
    if current_state == State.STATE_9_OOD.value:
        return "COMPLETED"

    # Default
    return "INIT"


# УДАЛЕНО: _detect_user_confirmation перенесена в fsm/facts.py
# УДАЛЕНО: _determine_next_state удалена - используем core.state_machine.get_next_state() как SSOT
# УДАЛЕНО: _determine_response_policy перенесена в fsm/policy.py (использует manifest.json)


def _format_transition_reason(
    from_state: str,
    to_state: str,
    intent: str,
    user_confirmed: bool,
    payment_sub_phase: str | None,
    strict_state5_override: bool = False,
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

    if strict_state5_override:
        parts.append("strict_state5_short_ack_override")
    
    return "|".join(parts) if parts else "no_change"


def _is_state5_short_ack_not_cancel(user_message: str | None) -> bool:
    """True for short acknowledgements in payment flow, excluding explicit cancels/refusals."""
    if not user_message:
        return False

    text = user_message.lower().strip()
    if not text:
        return False

    if any(marker in text for marker in _STATE5_EXPLICIT_CANCEL_MARKERS):
        return False

    # Normalize punctuation around short replies.
    normalized = re.sub(r"[!?.…,]+", "", text).strip()
    if normalized in _STATE5_SHORT_ACKS:
        return True

    # Guard for short variants like "так, дякую" or "ок, добре".
    tokens = [t for t in re.split(r"\s+", normalized) if t]
    if 1 <= len(tokens) <= 3 and all(t in _STATE5_SHORT_ACKS for t in tokens):
        return True

    return False

