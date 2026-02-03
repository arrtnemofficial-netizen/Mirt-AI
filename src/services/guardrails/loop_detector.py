"""
Loop detection and state transition guardrails.
===============================================
Extracts "safety net" logic from ConversationHandler to prevent
infinite loops or invalid state transitions.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.models import BaseConversationState as ConversationState
from src.core.state_machine import (
    State,
    VALID_DIALOG_PHASES,
    get_default_dialog_phase_for_state,
)
from src.services.observability import track_metric

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# VALID_DIALOG_PHASES imported from core.state_machine (SSOT). No local copy.


def _safe_hash(value: str) -> str:
    """Generate safe short hash for fingerprinting."""
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _guard_progress_fingerprint(state: ConversationState) -> str:
    """Create a hash of the current conversation state to detect stagnation."""
    meta = state.get("metadata", {}) or {}
    
    # Safe extraction of product lists (handling empty/None)
    selected = state.get("selected_products") or []
    offered = state.get("offered_products") or []
    
    payload = {
        "current_state": state.get("current_state"),
        "dialog_phase": state.get("dialog_phase"),
        "detected_intent": state.get("detected_intent"),
        "selected_products": [
            (p.get("id"), p.get("name"), p.get("size"), p.get("color"))
            for p in selected
            if isinstance(p, dict)
        ],
        "offered_products": [
            (p.get("id"), p.get("name"), p.get("size"), p.get("color"))
            for p in offered
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


def apply_loop_protection(
    *,
    session_id: str,
    before_state: ConversationState,
    after_state: ConversationState,
    user_text: str,
) -> ConversationState:
    """
    Apply safety guardrails to transition.
    
    1. Validates dialog_phase and current_state.
    2. Detects loops where state hasn't changed (fingerprint match).
    3. Handles soft recovery and escalation if loops persist.
    """
    
    # 1. Validation
    meta = after_state.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        after_state["metadata"] = meta

    dialog_phase = after_state.get("dialog_phase", "INIT")
    current_state = after_state.get("current_state", State.STATE_0_INIT.value)
    if (
        not dialog_phase
        or not isinstance(dialog_phase, str)
        or dialog_phase not in VALID_DIALOG_PHASES
    ):
        try:
            state_enum = State.from_string(str(current_state))
            correct_phase = get_default_dialog_phase_for_state(state_enum)
        except (ValueError, TypeError):
            correct_phase = "INIT"
        logger.error(
            "[SESSION %s] Guardrail: invalid dialog_phase=%r -> %s",
            session_id,
            dialog_phase,
            correct_phase,
        )
        after_state["dialog_phase"] = correct_phase

    current_state = after_state.get("current_state", State.STATE_0_INIT.value)
    # Normalize state to ensure it matches Enum values
    normalized_state = State.from_string(str(current_state)).value
    if current_state != normalized_state:
        logger.error(
            "[SESSION %s] Guardrail: invalid current_state=%r -> %s",
            session_id,
            current_state,
            normalized_state,
        )
        after_state["current_state"] = normalized_state

    # 2. Loop Detection
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

    # 3. Actions based on Loop Count
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
        # Soft reset logic
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

    if count >= 20:
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
        
        # Hard escalation logic
        after_state["dialog_phase"] = "COMPLAINT"
        after_state["current_state"] = State.STATE_8_COMPLAINT.value
        after_state["detected_intent"] = "COMPLAINT"
        after_state["escalation_reason"] = "Loop guard: too many repeated turns"
        after_state["should_escalate"] = True
        after_state["last_error"] = "loop_guard_escalation"
        
        try:
            from src.core.human_responses import get_human_response
            
            # Construct escalation response
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
            # Fallback if text replacement fails
            pass
            
        if settings.DEBUG_TRACE_LOGS:
            debug_log.error(
                session_id=session_id,
                error_type="LoopGuard",
                message=f"Escalation (count={count})",
            )

    # 4. Message Cleanup (Legacy logic kept for compatibility)
    # Checks for duplicate greetings etc.
    agent_response = after_state.get("agent_response")
    if isinstance(agent_response, dict):
        messages = agent_response.get("messages")
        if isinstance(messages, list):
            # No-op specific cleanup for now as per original code
            pass

    return after_state
