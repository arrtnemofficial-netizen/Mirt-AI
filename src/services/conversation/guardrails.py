"""FSM transition guardrails.

This module provides defense-in-depth validation for conversation state transitions.
It prevents invalid FSM transitions and detects conversation loops.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.services.core.observability import track_metric

if TYPE_CHECKING:
    from src.core.conversation_state import ConversationState

logger = logging.getLogger(__name__)


_ALLOWED_DIALOG_PHASES: set[str] = {
    "INIT",
    "DISCOVERY",
    "VISION_DONE",
    "WAITING_FOR_SIZE",
    "WAITING_FOR_COLOR",
    "SIZE_COLOR_DONE",
    "OFFER_MADE",
    "WAITING_FOR_DELIVERY_DATA",
    "WAITING_FOR_PAYMENT_METHOD",
    "WAITING_FOR_PAYMENT_PROOF",
    "UPSELL_OFFERED",
    "CRM_ERROR_HANDLING",
    "ESCALATED",
    "COMPLAINT",
    "OUT_OF_DOMAIN",
    "COMPLETED",
}


def _safe_hash(value: str) -> str:
    """Create a short hash of a string value."""
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _guard_progress_fingerprint(state: "ConversationState") -> str:
    """Create a fingerprint of the conversation progress for loop detection."""
    meta = state.get("metadata", {}) or {}
    payload = {
        "current_state": state.get("current_state"),
        "dialog_phase": state.get("dialog_phase"),
        "detected_intent": state.get("detected_intent"),
        "selected_products": [
            (p.get("id"), p.get("name"), p.get("size"), p.get("color"))
            for p in (state.get("selected_products") or [])
            if isinstance(p, dict)
        ],
        "offered_products": [
            (p.get("id"), p.get("name"), p.get("size"), p.get("color"))
            for p in (state.get("offered_products") or [])
            if isinstance(p, dict)
        ],
        "customer": {
            "name": meta.get("customer_name"),
            "phone": meta.get("customer_phone"),
            "city": meta.get("customer_city"),
            "nova_poshta": meta.get("customer_nova_poshta"),
        },
        "payment": {
            "payment_details_sent": meta.get("payment_details_sent"),
            "awaiting_payment_confirmation": meta.get("awaiting_payment_confirmation"),
            "payment_confirmed": meta.get("payment_confirmed"),
            "payment_proof_received": meta.get("payment_proof_received"),
        },
        "crm": {
            "crm_external_id": state.get("crm_external_id"),
            "crm_retry_count": state.get("crm_retry_count"),
            "crm_status": (state.get("crm_order_result") or {}).get("status"),
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return _safe_hash(raw)


def apply_transition_guardrails(
    *,
    session_id: str,
    before_state: "ConversationState",
    after_state: "ConversationState",
    user_text: str,
) -> "ConversationState":
    """Apply FSM transition guardrails to prevent invalid state changes.

    This function validates and potentially corrects state transitions,
    detects conversation loops, and triggers escalation when needed.
    """
    from src.core.state_machine import (
        Intent,
        State,
        expected_state_for_phase,
        is_transition_allowed,
    )

    meta = after_state.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        after_state["metadata"] = meta

    # Validate dialog_phase
    dialog_phase = after_state.get("dialog_phase", "INIT")
    if (
        not dialog_phase
        or not isinstance(dialog_phase, str)
        or dialog_phase not in _ALLOWED_DIALOG_PHASES
    ):
        logger.error(
            "[SESSION %s] Guardrail: invalid dialog_phase=%r -> INIT",
            session_id,
            dialog_phase,
        )
        after_state["dialog_phase"] = "INIT"
        dialog_phase = "INIT"

    if dialog_phase == "ESCALATED":
        logger.warning("[SESSION %s] Guardrail: ESCALATED -> COMPLETED", session_id)
        after_state["dialog_phase"] = "COMPLETED"
        dialog_phase = "COMPLETED"

    # Normalize current_state
    current_state = after_state.get("current_state", State.STATE_0_INIT.value)
    normalized_state = State.from_string(str(current_state)).value
    if current_state != normalized_state:
        logger.error(
            "[SESSION %s] Guardrail: invalid current_state=%r -> %s",
            session_id,
            current_state,
            normalized_state,
        )
        after_state["current_state"] = normalized_state

    # Check phase-state consistency
    expected_state = expected_state_for_phase(dialog_phase)
    if expected_state and after_state.get("current_state") != expected_state.value:
        logger.warning(
            "[SESSION %s] FSM guard: phase=%s expected_state=%s got=%s",
            session_id,
            dialog_phase,
            expected_state.value,
            after_state.get("current_state"),
        )
        track_metric(
            "fsm_guard_phase_override",
            1,
            {
                "phase": str(dialog_phase),
                "expected_state": expected_state.value,
                "actual_state": str(after_state.get("current_state") or ""),
            },
        )
        after_state["current_state"] = expected_state.value
        meta["current_state"] = expected_state.value

    # Validate transition
    before_state_enum = State.from_string(str(before_state.get("current_state")))
    after_state_enum = State.from_string(str(after_state.get("current_state")))
    intent_raw = (
        after_state.get("detected_intent")
        or meta.get("intent")
        or before_state.get("detected_intent")
        or ""
    )
    intent_enum = Intent.from_string(str(intent_raw))

    if not is_transition_allowed(
        from_state=before_state_enum,
        to_state=after_state_enum,
        intent=intent_enum,
        dialog_phase=dialog_phase,
    ):
        fallback_state = expected_state or before_state_enum
        logger.error(
            "[SESSION %s] FSM guard: blocked transition %s -> %s (intent=%s phase=%s), fallback=%s",
            session_id,
            before_state_enum.value,
            after_state_enum.value,
            intent_enum.value,
            dialog_phase,
            fallback_state.value,
        )
        track_metric(
            "fsm_guard_transition_blocked",
            1,
            {
                "from_state": before_state_enum.value,
                "to_state": after_state_enum.value,
                "intent": intent_enum.value,
                "phase": str(dialog_phase),
            },
        )
        after_state["current_state"] = fallback_state.value
        meta["current_state"] = fallback_state.value

    # Loop detection
    guard = meta.get("_guard")
    if not isinstance(guard, dict):
        guard = {}

    before_fp = _guard_progress_fingerprint(before_state)
    after_fp = _guard_progress_fingerprint(after_state)
    prev_count = int(guard.get("count") or 0)

    stagnant_this_turn = before_fp == after_fp
    count = (prev_count + 1) if stagnant_this_turn else 0

    guard["fp"] = after_fp
    guard["count"] = count
    guard["last_user_hash"] = _safe_hash(user_text.strip().lower())
    guard["before_fp"] = before_fp
    meta["_guard"] = guard

    # Loop warnings and recovery
    if count == 5:
        track_metric(
            "loop_guard_warn",
            1,
            {
                "phase": str(after_state.get("dialog_phase") or ""),
                "state": str(after_state.get("current_state") or ""),
            },
        )
        logger.warning(
            "[SESSION %s] Guardrail: potential loop (count=%d, phase=%s, state=%s)",
            session_id,
            count,
            after_state.get("dialog_phase"),
            after_state.get("current_state"),
        )

    if count == 10:
        track_metric(
            "loop_guard_soft_recovery",
            1,
            {
                "phase": str(after_state.get("dialog_phase") or ""),
                "state": str(after_state.get("current_state") or ""),
            },
        )
        logger.error(
            "[SESSION %s] Guardrail: loop detected -> soft recovery to INIT (count=%d)",
            session_id,
            count,
        )
        after_state["dialog_phase"] = "INIT"
        after_state["current_state"] = State.STATE_0_INIT.value
        after_state["detected_intent"] = None
        after_state["last_error"] = "loop_guard_soft_recovery"
        if settings.DEBUG_TRACE_LOGS:
            debug_log.error(
                session_id=session_id,
                error_type="LoopGuard",
                message=f"Soft recovery to INIT (count={count})",
            )

    current_phase = after_state.get("dialog_phase", "INIT")

    if count >= settings.LOOP_GUARD_WARNING_THRESHOLD:
        if settings.DEBUG_TRACE_LOGS:
            debug_log.warning(
                session_id=session_id,
                message=f"Loop warning (phase={current_phase}, count={count})",
            )

    if count >= settings.LOOP_GUARD_SOFT_RESET and count < settings.LOOP_GUARD_ESCALATION:
        if settings.DEBUG_TRACE_LOGS:
            debug_log.warning(
                session_id=session_id,
                message=f"Loop soft reset (phase={current_phase}, count={count})",
            )

    if count >= settings.LOOP_GUARD_ESCALATION:
        track_metric(
            "loop_guard_escalation",
            1,
            {
                "phase": str(after_state.get("dialog_phase") or ""),
                "state": str(after_state.get("current_state") or ""),
            },
        )
        logger.error(
            "[SESSION %s] Guardrail: loop detected -> escalation (count=%d)",
            session_id,
            count,
        )
        after_state["dialog_phase"] = "COMPLAINT"
        after_state["current_state"] = State.STATE_8_COMPLAINT.value
        after_state["detected_intent"] = "COMPLAINT"
        after_state["escalation_reason"] = "Loop guard: too many repeated turns"
        after_state["should_escalate"] = True
        after_state["last_error"] = "loop_guard_escalation"
        try:
            from src.core.human_responses import get_human_response

            after_state["agent_response"] = {
                "event": "escalation",
                "messages": [{"type": "text", "content": get_human_response("escalation")}],
                "metadata": {
                    "session_id": session_id,
                    "current_state": State.STATE_8_COMPLAINT.value,
                    "intent": "COMPLAINT",
                    "escalation_level": "L1",
                },
                "escalation": {
                    "reason": after_state.get("escalation_reason") or "Loop guard",
                    "target": "human_operator",
                },
            }
        except Exception:
            pass
        if settings.DEBUG_TRACE_LOGS:
            debug_log.error(
                session_id=session_id,
                error_type="LoopGuard",
                message=f"Escalation (count={count})",
            )

    # Defense-in-Depth log
    agent_response = after_state.get("agent_response")
    if isinstance(agent_response, dict):
        messages = agent_response.get("messages")
        if isinstance(messages, list):
            text_messages = [
                m for m in messages if isinstance(m, dict) and (m.get("type") in (None, "text"))
            ]
            first = text_messages[0] if text_messages else None
            first_content = first.get("content") if isinstance(first, dict) else None
            if isinstance(first_content, str):
                if settings.DEBUG_TRACE_LOGS:
                    debug_log.node_exit(
                        session_id=session_id,
                        node_name="guardrail_check",
                        goto="end",
                        new_phase=after_state.get("dialog_phase"),
                        response_preview=str(first_content)[:50],
                    )

    return after_state


# Backward compatibility alias
_apply_transition_guardrails = apply_transition_guardrails

