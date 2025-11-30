"""
Moderation Node - Safety gate.
==============================
First line of defense. Blocks inappropriate content.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.services.moderation import moderate_user_message
from src.services.observability import log_moderation_result, track_metric


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

    # No message to moderate
    if not user_content:
        return {
            "moderation_result": {"allowed": True, "flags": [], "reason": None},
            "step_number": state.get("step_number", 0) + 1,
        }

    # Run moderation
    result = moderate_user_message(user_content)

    updates: dict[str, Any] = {
        "moderation_result": {
            "allowed": result.allowed,
            "flags": result.flags,
            "redacted_text": result.redacted_text,
            "reason": result.reason,
        },
        "step_number": state.get("step_number", 0) + 1,
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
