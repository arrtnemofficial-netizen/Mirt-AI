"""
Escalation Node - Human handoff.
================================
When the bot can't handle it, hand off to human.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.models import AgentResponse, DebugInfo, Escalation, Message, Metadata
from src.core.state_machine import State
from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service
from src.services.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


def _get_escalation_response() -> str:
    """Get human-like escalation message."""
    from src.core.human_responses import get_human_response
    return get_human_response("escalation")


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
    reason = state.get("escalation_reason")
    if not reason:
        if state.get("retry_count", 0) >= state.get("max_retries", 3):
            reason = "Перевищено кількість спроб"
        elif state.get("moderation_result", {}).get("allowed") is False:
            reason = state.get("moderation_result", {}).get("reason", "Модерація")
        else:
            reason = "Потрібна допомога оператора"

    # Build escalation response
    response = AgentResponse(
        event="escalation",
        messages=[
            Message(
                content=(
                    _get_escalation_response()
                )
            )
        ],
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
    track_metric(
        "escalation_triggered",
        1,
        {
            "session_id": session_id,
            "reason": reason[:50] if reason else "unknown",
        },
    )

    logger.warning("Escalation for session %s: %s", session_id, reason)

    # =========================================================================
    # NOTIFY MANAGER
    # =========================================================================
    try:
        from src.services.notification_service import NotificationService

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

    # =========================================================================
    # SITNIKS: Set status to "AI Увага" and assign to human manager
    # =========================================================================
    try:
        sitniks_service = get_sitniks_chat_service()
        if sitniks_service.enabled:
            sitniks_result = await sitniks_service.handle_escalation(session_id)
            logger.info(
                "[SESSION %s] Sitniks escalation: %s",
                session_id,
                sitniks_result,
            )
    except Exception as e:
        logger.warning("[SESSION %s] Sitniks escalation error: %s", session_id, e)

    # =====================================================
    # DIALOG PHASE (Turn-Based State Machine)
    # =====================================================
    # STATE_8_COMPLAINT / STATE_9_OOD → ескалація
    #
    # Після ескалації встановлюємо COMPLETED
    # - Діалог передано менеджеру
    # =====================================================
    return {
        "current_state": State.STATE_8_COMPLAINT.value,
        "messages": [{"role": "assistant", "content": response.model_dump_json()}],
        "metadata": response.metadata.model_dump(),
        "dialog_phase": "COMPLETED",
        "should_escalate": True,
        "escalation_reason": reason,
        "step_number": state.get("step_number", 0) + 1,
    }
