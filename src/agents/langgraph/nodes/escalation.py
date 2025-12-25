"""
Escalation Node - Human handoff.
================================
When the bot can't handle it, hand off to human.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.models import AgentResponse, DebugInfo, Escalation, Message, Metadata
from src.core.prompt_registry import load_yaml_from_registry
from src.core.registry_keys import SystemKeys
from src.core.state_machine import State
from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service
from src.services.core.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


async def escalation_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Handle escalation to human operator.

    Triggered by:
    - Moderation blocks
    - Complaints
    - Out of domain requests
    - Too many retries
    """
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    current_state = state.get("current_state", State.STATE_0_INIT.value)

    # Determine escalation reason
    from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header

    def _get_reason(snippet_name: str, default: str) -> str:
        s = get_snippet_by_header(snippet_name)
        return s[0] if s else default

    reason = state.get("escalation_reason")
    if not reason:
        if state.get("retry_count", 0) >= state.get("max_retries", 3):
            reason = _get_reason("ESCALATION_REASON_RETRIES", "Maximum attempts exceeded")
        elif state.get("moderation_result", {}).get("allowed") is False:
            reason = state.get("moderation_result", {}).get("reason") or _get_reason("ESCALATION_REASON_MODERATION", "Moderation")
        else:
            reason = _get_reason("ESCALATION_REASON_OPERATOR", "Operator assistance required")

    # Build escalation response
    texts = load_yaml_from_registry(SystemKeys.TEXTS.value)
    esc_text = ""
    if isinstance(texts, dict):
        esc_text = texts.get("escalation", {}).get("message", "")
    if not esc_text:
        esc_text = "Your request was handed off to a manager."

    response = AgentResponse(
        event="escalation",
        messages=[Message(content=esc_text)],
        products=[],
        metadata=Metadata(
            session_id=session_id,
            current_state=State.STATE_8_COMPLAINT.value,
            intent="COMPLAINT",
            escalation_level="L1",
        ),
        escalation=Escalation(
            level="L1",
            reason=reason,
            target="human_operator",
        ),
        debug=DebugInfo(state=current_state, intent="escalation"),
    )

    # Log escalation
    log_agent_step(
        session_id=session_id,
        state=State.STATE_8_COMPLAINT.value,
        intent="COMPLAINT",
        event="escalation",
        escalation_level="L1",
        extra={"reason": reason},
    )
    track_metric("escalation_triggered", 1, {
        "session_id": session_id,
        "reason": reason[:50] if reason else "unknown",
    })

    logger.warning("Escalation for session %s: %s", session_id, reason)

    # =========================================================================
    # NOTIFY MANAGER
    # =========================================================================
    try:
        from src.services.infra.notification_service import NotificationService

        notifier = NotificationService()
        
        # Get last user message for context
        messages = state.get("messages", [])
        user_context = None
        if messages:
            # Try to find last user message
            for m in reversed(messages):
                if isinstance(m, dict) and m.get("role") == "user":
                    user_context = m.get("content")
                    break
                elif hasattr(m, "type") and m.type == "human":
                    user_context = m.content
                    break

        await notifier.send_escalation_alert(session_id, reason, user_context)
    except Exception as e:
        logger.error("Failed to send manager notification: %s", e)

    # Determine dialog_phase based on current_state
    # If already in COMPLAINT state, keep COMPLAINT phase
    # Otherwise, escalation node sets STATE_8_COMPLAINT, so use COMPLAINT phase
    dialog_phase = "COMPLAINT"
    if current_state == State.STATE_9_OOD.value:
        dialog_phase = "OUT_OF_DOMAIN"
    
    return {
        "current_state": State.STATE_8_COMPLAINT.value,
        "dialog_phase": dialog_phase,
        "messages": [{"role": "assistant", "content": response.model_dump_json()}],
        "metadata": response.metadata.model_dump(),
        "should_escalate": True,
        "escalation_reason": reason,
        "step_number": state.get("step_number", 0) + 1,
    }
