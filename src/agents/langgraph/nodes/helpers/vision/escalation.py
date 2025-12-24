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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.core.state_machine import State

if TYPE_CHECKING:
    from src.agents.pydantic.models import VisionResponse

logger = logging.getLogger(__name__)

# Module-level tracking to prevent duplicate escalations
# This is shared across all vision node calls
# SAFETY: Limited size to prevent memory leak (FIFO eviction)
_MAX_ACTIVE_ESCALATIONS = 1000
_ACTIVE_ESCALATIONS: set[str] = set()


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
    confidence = response.confidence or 0.0
    claimed_name = (
        getattr(response.identified_product, "name", None)
        if response.identified_product
        else None
    )

    product_not_in_catalog = response.identified_product is not None and catalog_row is None
    no_product_identified = response.identified_product is None or (
        response.identified_product
        and (response.identified_product.name or "") in ("<not identified>", "<none>", "")
    )

    low_confidence = confidence < confidence_threshold

    # Escalate if:
    # 1. Product identified but NOT in catalog (hallucination/competitor)
    # 2. Product NOT identified AND confidence is low (even if needs_clarification=True)
    #    Reason: User already sent photo, asking for clarification again is poor UX
    should_escalate = product_not_in_catalog or (no_product_identified and low_confidence)

    # SAFETY: If confidence is VERY low (< 0.5), always escalate regardless of needs_clarification
    # This prevents infinite clarification loops
    if no_product_identified and confidence < 0.5:
        should_escalate = True
        logger.info(
            "🚨 Force escalation: very low confidence (%.0f%%) even with needs_clarification",
            confidence * 100,
        )

    # Determine escalation reason
    if product_not_in_catalog:
        reason = "product_not_in_catalog"
    elif no_product_identified:
        reason = "product_not_identified"
    else:
        reason = "low_confidence"

    return should_escalate, reason


def build_escalation_state_update(
    state: dict[str, Any],
    session_id: str,
    trace_id: str,
    user_message: str,
    image_url: str | None,
    escalation_reason: str,
    confidence: float,
    claimed_name: str | None,
    create_task_fn: Callable[[asyncio.coroutine], asyncio.Task] | None = None,
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
    from .utils import text_msg

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

    # SAFETY: Prevent duplicate escalations for the same session
    session_key = f"{session_id}_vision_escalation"
    if session_key in active_escalations:
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

    # Add to active escalations BEFORE creating task to prevent race condition
    # SAFETY: Prevent memory leak by limiting set size (FIFO eviction)
    if len(active_escalations) >= _MAX_ACTIVE_ESCALATIONS:
        # Remove oldest entries (simple FIFO - remove first item)
        oldest = next(iter(active_escalations), None)
        if oldest:
            active_escalations.discard(oldest)
            logger.warning(
                "Active escalations set full (%d), evicted oldest: %s",
                _MAX_ACTIVE_ESCALATIONS,
                oldest,
            )
    active_escalations.add(session_key)

    async def _send_notification_background() -> None:
        try:
            from src.services.notification_service import NotificationService

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
        except Exception as notif_err:
            logger.warning("Failed to send Telegram notification: %s", notif_err)
        finally:
            # Remove from active escalations after completion
            active_escalations.discard(session_key)

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

