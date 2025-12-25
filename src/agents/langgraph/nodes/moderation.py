"""
Moderation Node - Safety gate.
==============================
First line of defense. Blocks inappropriate content.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.services.core.moderation import moderate_user_message
from src.services.core.observability import log_moderation_result, track_metric


logger = logging.getLogger(__name__)


async def moderation_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Check user message for safety issues.

    This node:
    1. Extracts latest user message
    2. Runs through moderation service
    3. Sets escalation flag if blocked
    4. Returns partial state update

    Returns:
        State update with moderation_result and possibly should_escalate
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # Get latest user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message
    user_content = extract_user_message(state.get("messages", []))
    
    # Check if this is a NEW message (new turn) vs continuation
    # If user sent new content, clear old escalation flag from previous turn
    has_image = state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
    is_new_message = has_image or bool(user_content)
    
    updates: dict[str, Any] = {
        "step_number": state.get("step_number", 0) + 1,
    }
    
    # Clear escalation flag for new messages to allow normal processing
    if is_new_message and state.get("should_escalate"):
        logger.debug(
            "Clearing should_escalate flag for new message (has_image=%s, has_text=%s)",
            has_image,
            bool(user_content),
        )
        updates["should_escalate"] = False
        updates["escalation_reason"] = None

    # No message to moderate
    if not user_content:
        updates["moderation_result"] = {"allowed": True, "flags": [], "reason": None}
        return updates

    # Run moderation
    result = moderate_user_message(user_content)

    updates["moderation_result"] = {
        "allowed": result.allowed,
        "flags": result.flags,
        "redacted_text": result.redacted_text,
        "reason": result.reason,
    }

    # Block if not allowed
    if not result.allowed:
        updates["should_escalate"] = True
        updates["escalation_reason"] = result.reason or "Moderation blocked"
        logger.warning(
            "Moderation blocked message for session %s: %s",
            session_id,
            result.reason,
        )

    # Observability
    log_moderation_result(
        session_id=session_id,
        allowed=result.allowed,
        flags=result.flags,
        reason=result.reason,
    )
    track_metric(
        "moderation_latency_ms",
        (time.perf_counter() - start_time) * 1000,
        {"allowed": str(result.allowed), "session_id": session_id},
    )

    return updates
