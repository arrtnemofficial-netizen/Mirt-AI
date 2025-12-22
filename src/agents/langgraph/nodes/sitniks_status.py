"""Sitniks CRM status update node.

This node automatically updates Sitniks CRM chat statuses based on conversation stage.
Called after agent node to keep CRM in sync with conversation state.

Stages handled:
- first_touch: Set "Взято в роботу" + assign AI Manager
- give_requisites: Set "Виставлено рахунок"
- escalation: Set "AI Увага" + assign human manager
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def update_sitniks_status(state: dict[str, Any]) -> dict[str, Any]:
    """Update Sitniks CRM status based on conversation stage.

    This node:
    1. Checks state.metadata.stage or state.stage
    2. Calls appropriate Sitniks service method
    3. Logs errors but doesn't break the graph

    Args:
        state: Current conversation state

    Returns:
        State update (usually empty, just passes through)
    """
    try:
        from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service
        from src.workers.sync_utils import run_sync

        # Get stage from state
        metadata = state.get("metadata", {})
        stage = metadata.get("stage") or state.get("stage")
        
        if not stage:
            # No stage to process
            return {"step_number": state.get("step_number", 0) + 1}

        # Get user_id from state
        user_id = metadata.get("user_id") or state.get("user_id")
        if not user_id:
            logger.warning("[SITNIKS:NODE] No user_id in state, skipping status update")
            return {"step_number": state.get("step_number", 0) + 1}

        # Get Instagram username if available
        instagram_username = metadata.get("instagram_username") or state.get("instagram_username")
        telegram_username = metadata.get("telegram_username") or state.get("telegram_username")

        service = get_sitniks_chat_service()
        if not service.enabled:
            logger.debug("[SITNIKS:NODE] Sitniks service not enabled, skipping")
            return {"step_number": state.get("step_number", 0) + 1}

        stage_lower = str(stage).lower().replace("-", "_").replace(" ", "_")

        # Handle different stages
        if stage_lower == "first_touch":
            logger.info("[SITNIKS:NODE] Handling first_touch for user %s", user_id)
            async def _handle():
                return await service.handle_first_touch(
                    user_id=str(user_id),
                    instagram_username=instagram_username,
                    telegram_username=telegram_username,
                )
            result = run_sync(_handle())
            logger.info("[SITNIKS:NODE] First touch result: %s", result)

        elif stage_lower == "give_requisites" or stage_lower == "give_requisits":
            logger.info("[SITNIKS:NODE] Handling give_requisites for user %s", user_id)
            async def _handle():
                return await service.handle_invoice_sent(str(user_id))
            result = run_sync(_handle())
            logger.info("[SITNIKS:NODE] Invoice sent result: %s", result)

        elif stage_lower == "escalation":
            logger.info("[SITNIKS:NODE] Handling escalation for user %s", user_id)
            async def _handle():
                return await service.handle_escalation(str(user_id))
            result = run_sync(_handle())
            logger.info("[SITNIKS:NODE] Escalation result: %s", result)

        else:
            logger.debug("[SITNIKS:NODE] Unknown stage '%s', skipping", stage)

        return {"step_number": state.get("step_number", 0) + 1}

    except Exception as e:
        # Don't break the graph on Sitniks errors
        logger.exception("[SITNIKS:NODE] Error updating Sitniks status: %s", e)
        return {"step_number": state.get("step_number", 0) + 1}

