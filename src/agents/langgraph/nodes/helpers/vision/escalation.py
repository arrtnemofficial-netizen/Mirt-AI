"""
Vision Escalation - Dual-track escalation logic.

This module handles escalation decisions and state updates for vision node.
Extracted from vision.py for better testability and maintainability.

Dual-track escalation:
- User gets soft message (greeting + "will check availability")
- Manager gets Telegram notification immediately (background task)
- Prevents duplicate escalations per session
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from src.core.state_machine import State
from src.services.vision import evaluate_vision_escalation

from ...utils import text_msg


if TYPE_CHECKING:
    from src.agents.pydantic.models import VisionResponse

logger = logging.getLogger(__name__)

# Module-level tracking to prevent duplicate escalations
# This is shared across all vision node calls
# SAFETY: Limited size to prevent memory leak (FIFO eviction)
_MAX_ACTIVE_ESCALATIONS = 1000
_ACTIVE_ESCALATIONS: set[str] = set()


def try_start_escalation(
    session_key: str,
    active_escalations: set[str] | None = None,
) -> bool:
    """Mark escalation as active, returns False for duplicate session key."""
    active = _ACTIVE_ESCALATIONS if active_escalations is None else active_escalations
    if session_key in active:
        return False
    if len(active) >= _MAX_ACTIVE_ESCALATIONS:
        oldest = next(iter(active), None)
        if oldest:
            active.discard(oldest)
            logger.warning(
                "Active escalations set full (%d), evicted oldest: %s",
                _MAX_ACTIVE_ESCALATIONS,
                oldest,
            )
    active.add(session_key)
    return True


def finish_escalation(
    session_key: str,
    active_escalations: set[str] | None = None,
) -> None:
    """Remove escalation key from active set."""
    active = _ACTIVE_ESCALATIONS if active_escalations is None else active_escalations
    active.discard(session_key)


def should_escalate_vision(
    response: "VisionResponse",
    catalog_row: dict[str, Any] | None,
    confidence_threshold: float = 0.75,
) -> tuple[bool, str]:
    """
    Decide if vision should escalate based on response and catalog lookup.

    Escalates if:
    1. Product identified but NOT in catalog (hallucination/competitor)
    2. Product NOT identified AND confidence is low (< threshold)
    3. Confidence is VERY low (< 0.5) - always escalate regardless of needs_clarification

    Args:
        response: VisionResponse from vision agent
        catalog_row: Enriched product from catalog (None if not found)
        confidence_threshold: Minimum confidence threshold (default 0.75)

    Returns:
        Tuple of (should_escalate: bool, reason: str)
    """
    decision = evaluate_vision_escalation(
        response=response,
        catalog_row=catalog_row,
        confidence_threshold=confidence_threshold,
    )

    if decision.no_product_identified and decision.confidence < 0.5:
        should_escalate = True
        logger.info(
            "🚨 Force escalation: very low confidence (%.0f%%) even with needs_clarification",
            decision.confidence * 100,
        )
    else:
        should_escalate = decision.should_escalate

    return should_escalate, decision.reason


def build_escalation_state_update(
    state: dict[str, Any],
    session_id: str,
    trace_id: str,
    user_message: str,
    image_url: str | None,
    escalation_reason: str,
    confidence: float,
    claimed_name: str | None,
    create_task_fn: Callable[[Coroutine[Any, Any, None]], asyncio.Task] | None = None,
    active_escalations: set[str] | None = None,
    bg_tasks: set[asyncio.Task] | None = None,
) -> dict[str, Any]:
    """
    Build state update for vision escalation with dual-track notification.

    Args:
        state: Current conversation state
        session_id: Session ID
        trace_id: Trace ID for observability
        user_message: User's message text
        image_url: Image URL from deps
        escalation_reason: Reason for escalation (from should_escalate_vision)
        confidence: Vision confidence score
        claimed_name: Product name claimed by vision (if any)
        create_task_fn: Function to create async task (default: asyncio.create_task)
        active_escalations: Set to track active escalations (default: module-level)
        bg_tasks: Set to track background tasks (optional, for cleanup)

    Returns:
        State update dict with escalation info
    """
    if create_task_fn is None:
        create_task_fn = asyncio.create_task

    if active_escalations is None:
        active_escalations = _ACTIVE_ESCALATIONS

    # STANDARD ESCALATION MESSAGE: Only greeting + "will check availability"
    # Do NOT ask for more details - manager will handle it
    escalation_messages = [
        text_msg("Вітаю 🎀 З вами MIRT_UA, менеджер Софія."),
        text_msg("Зараз уточню по цьому товару наявність 🙌🏻"),
    ]

    session_key = f"{session_id}_vision_escalation"
    if not try_start_escalation(session_key, active_escalations):
        logger.warning(
            "🚨 [SESSION %s] Escalation already in progress, skipping duplicate",
            session_id,
        )
        # Return early without creating task
        return {
            "current_state": State.STATE_0_INIT.value,
            "messages": escalation_messages,
            "selected_products": [],
            "dialog_phase": "ESCALATED",
            "has_image": False,
            "escalation_level": "L1",
            "metadata": {
                **state.get("metadata", {}),
                "vision_confidence": confidence,
                "needs_clarification": False,
                "has_image": False,
                "vision_greeted": True,
                "escalation_level": "L1",
                "escalation_reason": escalation_reason,
                "escalation_mode": "SOFT",
            },
            "agent_response": {
                "messages": escalation_messages,
                "metadata": {
                    "session_id": session_id,
                    "current_state": State.STATE_0_INIT.value,
                    "intent": "PHOTO_IDENT",
                    "escalation_level": "L1",
                    "notes": "escalation_mode=SOFT",
                },
            },
            "step_number": state.get("step_number", 0) + 1,
        }

    async def _send_notification_background() -> None:
        try:
            from src.services.notifications import NotificationService

            notification = NotificationService()
            reason_parts = []
            if escalation_reason == "product_not_in_catalog":
                reason_parts.append("Товар не знайдено в каталозі")
            if escalation_reason == "product_not_identified":
                reason_parts.append("Товар не ідентифіковано")
            if escalation_reason == "low_confidence":
                reason_parts.append(f"Низька впевненість ({confidence*100:.0f}%)")
            reason_text = " / ".join(reason_parts) if reason_parts else "Товар не знайдено"

            await notification.send_escalation_alert(
                session_id=session_id or "unknown",
                reason=reason_text,
                user_context=user_message,
                details={
                    "trace_id": trace_id,
                    "dialog_phase": "ESCALATED",
                    "current_state": State.STATE_0_INIT.value,
                    "intent": "PHOTO_IDENT",
                    "confidence": confidence * 100,
                    "image_url": image_url,
                    "vision_identified": claimed_name,
                    "escalation_reason": escalation_reason,
                },
            )
            logger.info(
                "📲 [SESSION %s] Telegram notification sent to manager (dual-track escalation)",
                session_id,
            )
        except (RuntimeError, OSError, ValueError, TypeError) as notif_err:
            logger.warning("Failed to send Telegram notification: %s", notif_err)
        finally:
            finish_escalation(session_key, active_escalations)

    task = create_task_fn(_send_notification_background())
    if bg_tasks is not None:
        bg_tasks.add(task)
        task.add_done_callback(bg_tasks.discard)

    return {
        "current_state": State.STATE_0_INIT.value,
        "messages": escalation_messages,
        "selected_products": [],
        "dialog_phase": "ESCALATED",
        "has_image": False,
        "escalation_level": "L1",  # SOFT escalation → L1 (contract-compliant)
        "manager_notification_sent": True,  # Flag to prevent duplicate notifications
        "metadata": {
            **state.get("metadata", {}),
            "vision_confidence": confidence,
            "needs_clarification": False,
            "has_image": False,
            "vision_greeted": True,
            "escalation_level": "L1",  # SOFT → L1
            "escalation_reason": escalation_reason,
            "escalation_mode": "SOFT",  # UX mode (soft/hard) stored separately
        },
        "agent_response": {
            "messages": escalation_messages,
            "metadata": {
                "session_id": session_id,
                "current_state": State.STATE_0_INIT.value,
                "intent": "PHOTO_IDENT",
                "escalation_level": "L1",  # SOFT → L1
                "notes": "escalation_mode=SOFT",  # UX mode in notes
            },
        },
        "step_number": state.get("step_number", 0) + 1,
    }

