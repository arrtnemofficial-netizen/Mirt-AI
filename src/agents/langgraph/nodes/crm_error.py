"""CRM Error Node - Handle CRM operation failures with available services."""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.types import Command

from src.services.core.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


async def crm_error_node(
    state: dict[str, Any],
) -> Command[Literal["payment", "upsell", "end", "crm_error"]]:
    """
    Simplified CRM Error Node.
    Does not rely on missing error_handler.py.
    """
    session_id = state.get("session_id", "")
    trace_id = state.get("trace_id", "")
    
    # Check if we're waiting for user choice
    if state.get("awaiting_user_choice"):
        return await _handle_user_choice(state, session_id)

    # Log error
    log_agent_step(
        session_id=session_id,
        state="CRM_ERROR_PRESENTED",
        intent="CRM_ERROR",
        event="error_shown",
        extra={"trace_id": trace_id},
    )

    error_details = str(state.get("last_error", "Unknown CRM error"))
    from src.integrations.crm.error_handler import get_crm_error_handler
    handler = get_crm_error_handler()
    
    result = await handler.escalate_to_operator(
        session_id=session_id,
        external_id=state.get("crm_external_id", "none"),
        error_details=error_details,
    )
    
    error_message = result.get("message", "Вибачте, сталася помилка при оформленні замовлення в CRM. Наш менеджер зв'яжеться з вами.")
    
    assistant_response = {
        "event": "simple_answer",
        "messages": [{"type": "text", "text": error_message}],
        "metadata": {
            "session_id": session_id,
            "crm_error": True,
        },
    }

    track_metric("crm_error_presented", 1, {"session_id": session_id})

    return Command(
        update={
            "messages": [{"role": "assistant", "content": error_message}],
            "agent_response": assistant_response,
            "awaiting_user_choice": True,
            "dialog_phase": "CRM_ERROR_HANDLING",
            "step_number": state.get("step_number", 0) + 1,
            "crm_retry_count": state.get("crm_retry_count", 0),
        },
        goto="crm_error",
    )


async def _handle_user_choice(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["payment", "end", "crm_error"]]:
    """Handle user input while in CRM error state."""
    # For now, just escalate all choices to end/operator
    logger.info("[CRM:ERROR] User message received in error state for session %s", session_id)
    
    final_message = "Дякую за терпіння. Менеджер вже займається вашим питанням."
    
    return Command(
        update={
            "messages": [{"role": "assistant", "content": final_message}],
            "awaiting_user_choice": False,
            "dialog_phase": "ESCALATED",
        },
        goto="end"
    )
