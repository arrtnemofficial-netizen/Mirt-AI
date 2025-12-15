"""Sitniks Status Node.

Post-response node that updates Sitniks CRM chat status based on conversation stage.

Stage → Status mapping:
- first_touch → "Взято в роботу" + assign AI Manager (Павло)
- give_requisites → "Виставлено рахунок"  
- escalation → "AI Увага" + assign human manager
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.types import Command

from src.core.state_machine import State
from src.integrations.crm.sitniks_chat_service import (
    get_sitniks_chat_service,
)


logger = logging.getLogger(__name__)


# Stage constants
STAGE_FIRST_TOUCH = "first_touch"
STAGE_GIVE_REQUISITES = "give_requisites"
STAGE_ESCALATION = "escalation"


def determine_stage(state: dict[str, Any]) -> str | None:
    """Determine current stage based on conversation state.
    
    Returns:
        Stage name or None if no status update needed
    """
    current_state = state.get("current_state", "")
    dialog_phase = state.get("dialog_phase", "")
    is_first_message = state.get("is_first_message", False)
    step_number = state.get("step_number", 0)

    # Check for escalation
    agent_response = state.get("agent_response", {})
    escalation = agent_response.get("escalation")
    if escalation:
        return STAGE_ESCALATION

    # Check escalation level in metadata
    metadata = agent_response.get("metadata", {})
    if metadata.get("escalation_level") not in (None, "NONE", ""):
        return STAGE_ESCALATION

    # First touch: first message from user OR step_number == 1
    if is_first_message or step_number <= 1:
        return STAGE_FIRST_TOUCH

    # Give requisites: payment state with requisites shown
    if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        if dialog_phase in ("SHOW_PAYMENT", "WAITING_FOR_PAYMENT_PROOF"):
            return STAGE_GIVE_REQUISITES

    # Check if response contains payment requisites
    messages = state.get("messages", [])
    if messages:
        last_msg = messages[-1] if isinstance(messages[-1], dict) else {}
        content = last_msg.get("content", "")
        if isinstance(content, str) and "IBAN" in content:
            return STAGE_GIVE_REQUISITES

    return None


async def sitniks_status_node(
    state: dict[str, Any],
) -> Command[Literal["__end__"]]:
    """Update Sitniks CRM status based on conversation stage.
    
    This node runs AFTER the agent response is generated but BEFORE
    the response is sent to the user.
    
    Flow:
    1. Determine stage (first_touch, give_requisites, escalation)
    2. Call appropriate Sitniks API
    3. Log result and continue
    """
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    metadata = state.get("metadata", {})

    # Get usernames from metadata
    instagram_username = metadata.get("instagram_username")
    telegram_username = metadata.get("user_nickname")  # We store Telegram username here

    # Determine what stage we're in
    stage = determine_stage(state)

    if not stage:
        # No status update needed
        return Command(
            update={"sitniks_status_updated": False},
            goto="__end__",
        )

    logger.info(
        "[SITNIKS_STATUS] Session %s stage: %s",
        session_id,
        stage,
    )

    service = get_sitniks_chat_service()

    if not service.enabled:
        logger.warning("[SITNIKS_STATUS] Service not enabled (no API access)")
        return Command(
            update={
                "sitniks_status_updated": False,
                "sitniks_stage": stage,
                "sitniks_error": "API not configured or no access",
            },
            goto="__end__",
        )

    result = {"success": False, "stage": stage}

    try:
        if stage == STAGE_FIRST_TOUCH:
            # First touch: find chat, set status, assign AI manager
            result = await service.handle_first_touch(
                user_id=session_id,
                instagram_username=instagram_username,
                telegram_username=telegram_username,
            )
            result["stage"] = stage

        elif stage == STAGE_GIVE_REQUISITES:
            # Invoice sent
            success = await service.handle_invoice_sent(session_id)
            result = {"success": success, "stage": stage}

        elif stage == STAGE_ESCALATION:
            # Escalation: set AI Attention, assign human manager
            result = await service.handle_escalation(session_id)
            result["stage"] = stage

    except Exception as e:
        logger.exception("[SITNIKS_STATUS] Error updating status: %s", e)
        result["error"] = str(e)

    logger.info(
        "[SITNIKS_STATUS] Result for session %s: %s",
        session_id,
        result,
    )

    return Command(
        update={
            "sitniks_status_updated": result.get("success", False),
            "sitniks_stage": stage,
            "sitniks_chat_id": result.get("chat_id"),
            "sitniks_result": result,
        },
        goto="__end__",
    )


async def sitniks_pre_response_node(
    state: dict[str, Any],
) -> dict[str, Any]:
    """Pre-response hook for first touch handling.
    
    This should run BEFORE sending the first response to ensure
    status is set before user sees the message.
    
    Only handles first_touch stage.
    """
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    metadata = state.get("metadata", {})
    step_number = state.get("step_number", 0)

    # Only process on first message
    if step_number > 1:
        return {"sitniks_first_touch_done": False}

    # Check if already processed
    if state.get("sitniks_first_touch_done"):
        return {}

    instagram_username = metadata.get("instagram_username")
    telegram_username = metadata.get("user_nickname")

    if not instagram_username and not telegram_username:
        logger.info("[SITNIKS_PRE] No username available for first touch")
        return {"sitniks_first_touch_done": True, "sitniks_no_username": True}

    service = get_sitniks_chat_service()

    if not service.enabled:
        return {"sitniks_first_touch_done": True, "sitniks_not_enabled": True}

    logger.info(
        "[SITNIKS_PRE] Handling first touch for session %s, username: %s",
        session_id,
        instagram_username or telegram_username,
    )

    try:
        result = await service.handle_first_touch(
            user_id=session_id,
            instagram_username=instagram_username,
            telegram_username=telegram_username,
        )

        return {
            "sitniks_first_touch_done": True,
            "sitniks_chat_id": result.get("chat_id"),
            "sitniks_first_touch_result": result,
        }

    except Exception as e:
        logger.exception("[SITNIKS_PRE] First touch error: %s", e)
        return {
            "sitniks_first_touch_done": True,
            "sitniks_first_touch_error": str(e),
        }
