"""CRM Error Node - Handle CRM operation failures.

Provides user-friendly error handling for CRM failures:
- Shows error messages based on failure type
- Offers retry options with automatic limits
- Escalates to operator after max retries
- Maintains conversation flow during error recovery
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.types import Command

from src.integrations.crm.error_handler import (
    get_crm_error_handler,
    retry_crm_order_in_state,
)
from src.services.observability import log_agent_step, track_metric


logger = logging.getLogger(__name__)


async def crm_error_node(
    state: dict[str, Any],
) -> Command[Literal["payment", "upsell", "end", "crm_error"]]:
    """
    Handle CRM operation errors with user-friendly recovery options.

    Flow:
    1. Analyze CRM error and determine recovery strategy
    2. Show appropriate error message to user
    3. Wait for user choice (retry/escalate)
    4. Process user choice and route accordingly

    Args:
        state: Current conversation state with CRM error info

    Returns:
        Command for next node based on error handling outcome
    """
    session_id = state.get("session_id", "")
    trace_id = state.get("trace_id", "")
    crm_order_result = state.get("crm_order_result", {})
    crm_external_id = state.get("crm_external_id", "")
    crm_retry_count = state.get("crm_retry_count", 0)

    logger.info(
        "[CRM:ERROR] Processing CRM error session=%s external_id=%s retry=%d status=%s",
        session_id,
        crm_external_id,
        crm_retry_count,
        crm_order_result.get("status", "unknown"),
    )

    # Check if we're waiting for user choice
    if state.get("awaiting_user_choice"):
        return await _handle_user_choice(state, session_id)

    # First entry - analyze error and show options
    return await _analyze_and_present_error(state, session_id, trace_id)


async def _analyze_and_present_error(
    state: dict[str, Any],
    session_id: str,
    trace_id: str = "",
) -> Command[Literal["crm_error"]]:
    """Analyze CRM error and present user with options."""
    crm_order_result = state.get("crm_order_result", {})
    crm_external_id = state.get("crm_external_id", "")
    crm_retry_count = state.get("crm_retry_count", 0)

    error = crm_order_result.get("error", "Unknown CRM error")
    error_code = crm_order_result.get("error_code")

    # Use error handler to analyze and generate response
    error_handler = get_crm_error_handler()
    error_result = await error_handler.handle_crm_failure(
        session_id=session_id,
        external_id=crm_external_id,
        error=error,
        error_code=error_code,
        retry_count=crm_retry_count,
    )

    # Log error handling
    log_agent_step(
        session_id=session_id,
        state="CRM_ERROR_HANDLING",
        intent="CRM_ERROR",
        event="error_analyzed",
        extra={
            "trace_id": trace_id,
            "error_strategy": error_result.get("strategy"),
            "can_retry": error_result.get("can_retry"),
            "retry_count": crm_retry_count,
        },
    )

    # Build user message
    user_message = error_result.get("message", "❌ Сталася помилка CRM")

    # Add retry options if available
    if error_result.get("can_retry"):
        user_message += "\n\nВідповідаючи, ви можете:\n"
        user_message += "• Написати 'повторити' або 'retry' для повторної спроби\n"
        user_message += "• Написати 'оператор' або 'escalate' для передачі оператору\n"
        user_message += "• Написати 'назад' для повернення до оформлення"

    # Create assistant response
    assistant_response = {
        "event": "simple_answer",
        "messages": [{"type": "text", "text": user_message}],
        "metadata": {
            "session_id": session_id,
            "crm_error": True,
            "error_strategy": error_result.get("strategy"),
        },
    }

    track_metric("crm_error_presented", 1, {
        "session_id": session_id,
        "strategy": error_result.get("strategy"),
        "retry_count": crm_retry_count,
    })

    # Update state and wait for user choice
    return Command(
        update={
            "messages": [{"role": "assistant", "content": user_message}],
            "agent_response": assistant_response,
            "crm_error_result": error_result,
            "awaiting_user_choice": True,
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="crm_error",  # Stay in error node to handle user response
    )


async def _handle_user_choice(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["payment", "upsell", "end", "crm_error"]]:
    """Handle user's choice for CRM error recovery."""
    from .utils import extract_user_message

    user_message = extract_user_message(state.get("messages", []))
    crm_external_id = state.get("crm_external_id", "")
    crm_error_result = state.get("crm_error_result", {})

    logger.info(
        "[CRM:ERROR] User choice for session %s: '%s'",
        session_id,
        user_message,
    )

    # Parse user intent
    user_intent = _parse_user_intent(user_message)

    if user_intent == "retry":
        return await _handle_retry_choice(state, session_id)
    elif user_intent == "escalate":
        return await _handle_escalate_choice(state, session_id)
    elif user_intent == "back":
        return await _handle_back_choice(state, session_id)
    else:
        # Unknown choice - show options again
        return await _show_options_again(state, session_id)


async def _handle_retry_choice(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["upsell", "crm_error"]]:
    """Handle user's choice to retry CRM operation."""
    logger.info("[CRM:ERROR] User chose retry for session %s", session_id)

    # Perform retry
    retry_result = await retry_crm_order_in_state(state)

    if retry_result.get("crm_retry_result", {}).get("success"):
        # Retry successful - proceed to upsell
        success_message = "✅ Замовлення успішно відправлено до CRM! Продовжуємо оформлення..."

        return Command(
            update={
                "messages": [{"role": "assistant", "content": success_message}],
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "text": success_message}],
                },
                "dialog_phase": "UPSELL_OFFERED",
                "awaiting_user_choice": False,
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="upsell",
        )
    else:
        # Retry failed - show error again
        error_message = retry_result.get("crm_retry_result", {}).get("message", "❌ Повторна спроба не вдалася")

        return Command(
            update={
                "messages": [{"role": "assistant", "content": error_message}],
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "text": error_message}],
                },
                "awaiting_user_choice": True,
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="crm_error",
        )


async def _handle_escalate_choice(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["end"]]:
    """Handle user's choice to escalate to operator."""
    logger.info("[CRM:ERROR] User chose escalation for session %s", session_id)

    error_handler = get_crm_error_handler()
    crm_external_id = state.get("crm_external_id", "")
    crm_error_result = state.get("crm_error_result", {})

    escalate_result = await error_handler.escalate_to_operator(
        session_id=session_id,
        external_id=crm_external_id,
        error_details=crm_error_result.get("message", "CRM operation failed"),
    )

    escalation_message = escalate_result.get("message", "📞 Замовлення передано оператору")

    track_metric("crm_error_escalated", 1, {"session_id": session_id})

    return Command(
        update={
            "messages": [{"role": "assistant", "content": escalation_message}],
            "agent_response": {
                "event": "simple_answer",
                "messages": [{"type": "text", "text": escalation_message}],
            },
            "dialog_phase": "ESCALATED",
            "awaiting_user_choice": False,
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="end",
    )


async def _handle_back_choice(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["payment"]]:
    """Handle user's choice to go back to payment/offer."""
    logger.info("[CRM:ERROR] User chose back for session %s", session_id)

    back_message = "🔙 Повертаємось до оформлення замовлення..."

    return Command(
        update={
            "messages": [{"role": "assistant", "content": back_message}],
            "agent_response": {
                "event": "simple_answer",
                "messages": [{"type": "text", "text": back_message}],
            },
            "dialog_phase": "OFFER_MADE",
            "awaiting_user_choice": False,
            "crm_order_result": None,  # Clear previous CRM result
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="payment",
    )


async def _show_options_again(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["crm_error"]]:
    """Show options again when user choice is unclear."""
    options_message = (
        "Не зрозумів вибір. Будь ласка, оберіть:\n\n"
        "• 'повторити' або 'retry' - для повторної спроби\n"
        "• 'оператор' або 'escalate' - для передачі оператору\n"
        "• 'назад' - для повернення до оформлення"
    )

    return Command(
        update={
            "messages": [{"role": "assistant", "content": options_message}],
            "agent_response": {
                "event": "simple_answer",
                "messages": [{"type": "text", "text": options_message}],
            },
            "awaiting_user_choice": True,
            "step_number": state.get("step_number", 0) + 1,
        },
        goto="crm_error",
    )


def _parse_user_intent(message: str) -> str:
    """Parse user intent from message."""
    if not message:
        return "unknown"

    message_lower = message.lower().strip()

    if any(word in message_lower for word in ["повторити", "retry", "знову", "спробувати"]):
        return "retry"
    elif any(word in message_lower for word in ["оператор", "escalate", "людина", "допомога"]):
        return "escalate"
    elif any(word in message_lower for word in ["назад", "back", "повернутись"]):
        return "back"
    else:
        return "unknown"
