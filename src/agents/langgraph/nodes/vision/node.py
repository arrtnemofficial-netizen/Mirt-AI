"""
Vision Node - Main Orchestrator.
================================
Coordinates the vision pipeline:
1. Prepares context
2. Calls Vision Agent
3. Enriches with Catalog Data
4. Builds UI Response
5. Handles Errors/Escalations
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.vision_agent import run_vision
from src.core.state_machine import State
from src.services.core.observability import log_agent_step, log_trace, track_metric

from ..utils import extract_user_message, text_msg
from .builder import (
    build_vision_error_escalation,
    build_vision_messages,
    extract_products,
)
from .enricher import enrich_product_from_db
from .snippets import get_snippet_by_header

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Keep strong references to background tasks to prevent GC
_BG_TASKS: set[asyncio.Task] = set()


async def vision_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,  # Kept for signature compatibility
) -> dict[str, Any]:
    """
    Process photo and identify product.

    This node:
    1. Extracts user message and image_url from state
    2. Calls run_vision (PydanticAI vision agent)
    3. Builds multi-bubble response using helper functions
    4. Updates state with results

    Args:
            state: Current conversation state
            runner: IGNORED - uses run_vision directly

    Returns:
            State update with identified products
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    trace_id = state.get("trace_id", "")
    messages = state.get("messages", [])

    # Extract user message
    user_message = extract_user_message(messages) or "Аналіз фото"

    # Build deps with image context
    deps = create_deps_from_state(state)
    deps.has_image = True
    deps.image_url = state.get("image_url") or state.get("metadata", {}).get("image_url")
    deps.current_state = State.STATE_2_VISION.value

    def _missing_vision_artifacts() -> list[str]:
        base = Path(__file__).parent.parent.parent.parent / "data" / "vision" / "generated"
        required = ["model_rules.yaml", "test_set.json"]
        missing = []
        for name in required:
            path = base / name
            if not path.exists() or path.stat().st_size == 0:
                missing.append(name)
        return missing
    def _normalize_text(value: str | None) -> str:
        text = (value or '').strip()
        if not text:
            return ''
        text = ' '.join(text.split())
        return text[:1].upper() + text[1:]
    def _get_greeting_bubble() -> str:
        snippet = get_snippet_by_header("Привітання")
        if snippet:
            return snippet[0]
        return "Вітаю 🎀 З вами MIRT_UA, менеджер Софія)!"


    # Helper for error escalation (notifications)
    def _handle_error_escalation(error_msg: str) -> dict[str, Any]:
        async def _send_notification_background() -> None:
            try:
                from src.services.infra.notification_service import NotificationService

                notification = NotificationService()
                await notification.send_escalation_alert(
                    session_id=session_id or "unknown",
                    reason="vision_error",
                    user_context=_normalize_text(user_message),
                    details={
                        "trace_id": trace_id,
                        "dialog_phase": "ESCALATED",
                        "current_state": State.STATE_0_INIT.value,
                        "intent": "PHOTO_IDENT",
                        "error": error_msg[:200],
                        "image_url": deps.image_url if deps else None,
                    },
                )
                logger.info("[SESSION %s] Telegram notification sent to manager", session_id)
            except Exception as notif_err:
                logger.warning("Failed to send Telegram notification: %s", notif_err)

        task = asyncio.create_task(_send_notification_background())
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)

        update = build_vision_error_escalation(error_msg, state.get("step_number", 0))
        # Add session_id to metadata which might be missing in pure builder
        update["agent_response"]["metadata"]["session_id"] = session_id
        return update

    def _handle_missing_artifacts(missing: list[str]) -> dict[str, Any]:
        async def _send_notification_background() -> None:
            try:
                from src.services.infra.notification_service import NotificationService

                notification = NotificationService()
                reason = (
                    "Відсутні артефакти Vision: "
                    + ", ".join(missing)
                    + ". Потрібно згенерувати data/vision/generate.py"
                )
                await notification.send_escalation_alert(
                    session_id=session_id or "unknown",
                    reason=reason,
                    user_context=_normalize_text(user_message),
                    details={
                        "trace_id": trace_id,
                        "dialog_phase": "ESCALATED",
                        "current_state": State.STATE_2_VISION.value,
                        "intent": "PHOTO_IDENT",
                        "missing_artifacts": missing,
                        "image_url": deps.image_url if deps else None,
                    },
                )
                logger.info("[SESSION %s] Telegram notification sent to manager", session_id)
            except Exception as notif_err:
                logger.warning("Failed to send Telegram notification: %s", notif_err)

        task = asyncio.create_task(_send_notification_background())
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)

        escalation_messages = [
            text_msg(_get_greeting_bubble()),
            text_msg(
                "Зараз цього товару немає в наявності — партія закінчилась. Можу перевірити, що найближче по стилю/кольору/розміру."
            ),
        ]

        return {
            "current_state": State.STATE_7_END.value,
            "messages": escalation_messages,
            "selected_products": [],
            "dialog_phase": "COMPLETED",
            "has_image": False,
            "escalation_level": "HARD",
            "metadata": {
                **state.get("metadata", {}),
                "vision_confidence": 0.0,
                "needs_clarification": False,
                "has_image": False,
                "vision_greeted": True,
                "vision_no_match_count": 0,
                "escalation_level": "HARD",
                "escalation_reason": "vision_artifacts_missing",
                "missing_artifacts": missing,
            },
            "agent_response": {
                "messages": escalation_messages,
                "metadata": {
                    "session_id": session_id,
                    "current_state": State.STATE_7_END.value,
                    "intent": "PHOTO_IDENT",
                    "escalation_level": "HARD",
                },
            },
            "step_number": state.get("step_number", 0) + 1,
        }

    logger.info(
        "🖼️ [SESSION %s] Vision node started: image=%s",
        session_id,
        deps.image_url[:60] if deps.image_url else "None",
    )


    try:
        # Call vision agent
        response = await run_vision(message=user_message, deps=deps)
    except Exception as e:
        err = str(e)
        logger.error("Vision agent error: %s", err)
        return _handle_error_escalation(err)

    metadata = state.get("metadata", {})
    no_match_count = int(metadata.get("vision_no_match_count") or 0)
    catalog_row: dict[str, Any] | None = None

    if response.identified_product or response.needs_clarification:
        if response.identified_product:
            try:
                enriched_row = await enrich_product_from_db(
                    response.identified_product.name,
                    color=response.identified_product.color,
                )
                if enriched_row and isinstance(enriched_row.get("_catalog_row"), dict):
                    catalog_row = enriched_row.get("_catalog_row")
                    try:
                        if isinstance(enriched_row.get("_color_options"), list):
                            catalog_row["_color_options"] = enriched_row.get("_color_options")
                        if "_ambiguous_color" in enriched_row:
                            catalog_row["_ambiguous_color"] = enriched_row.get("_ambiguous_color")
                    except Exception:
                        pass
            except Exception:
                catalog_row = None

        # =====================================================
        # CRITICAL: UNKNOWN PRODUCT = HARD ESCALATION!
        # =====================================================
        # ESCALATE if ANY of these conditions:
        # 1. Vision returned identified_product but NOT in our DB
        # 2. Vision returned NO product (identified_product is None)
        # 3. Low confidence (< 50%) regardless of alternatives
        # In ALL cases: DO NOT guess, ESCALATE to manager!
        # =====================================================
        confidence = response.confidence or 0.0

        # Case 2: AI couldn't identify anything (product is None or "<not identified>")
        no_product_identified = response.identified_product is None or (
            response.identified_product
            and response.identified_product.name in ("<not identified>", "<none>", "")
        )

        if no_product_identified and response.needs_clarification:
            no_match_count += 1
        no_match_limit = 2

        # Case 1: AI "identified" product but it's NOT in catalog (hallucination/competitor)
        product_not_in_catalog = response.identified_product is not None and catalog_row is None

        # Case 3: Low confidence - don't trust the result
        low_confidence = confidence < 0.5
        high_confidence_no_match = no_product_identified and confidence >= 0.85
        repeated_no_match = no_product_identified and no_match_count >= no_match_limit

        # ESCALATE if: not in catalog OR (no product AND low confidence)
        should_escalate = (
            product_not_in_catalog
            or (no_product_identified and low_confidence)
            or high_confidence_no_match
            or repeated_no_match
        )

        if no_product_identified and low_confidence and not metadata.get("vision_quality_retry"):
            retry_messages = [
                text_msg(_get_greeting_bubble()),
                text_msg(
                    "Щоб точно підібрати модель, скиньте, будь ласка, фото трохи ближче або світліше 🙏"
                ),
            ]
            return {
                "current_state": State.STATE_2_VISION.value,
                "messages": retry_messages,
                "selected_products": [],
                "dialog_phase": "VISION_RETRY",
                "has_image": True,
                "metadata": {
                    **metadata,
                    "vision_confidence": response.confidence,
                    "needs_clarification": True,
                    "has_image": True,
                    "vision_greeted": True,
                    "vision_no_match_count": no_match_count,
                    "vision_quality_retry": True,
                },
                "agent_response": {
                    "messages": retry_messages,
                    "metadata": {
                        "session_id": session_id,
                        "current_state": State.STATE_2_VISION.value,
                        "intent": "PHOTO_IDENT",
                    },
                },
                "step_number": state.get("step_number", 0) + 1,
            }

        if (no_product_identified or low_confidence):
            missing_artifacts = _missing_vision_artifacts()
            if missing_artifacts:
                logger.error("Vision artifacts missing: %s", missing_artifacts)
                return _handle_missing_artifacts(missing_artifacts)

        if should_escalate:
            logger.warning(
                "🚨 [SESSION %s] ESCALATION: Product not in catalog or low confidence! "
                "claimed='%s' confidence=%.0f%% catalog_found=%s",
                session_id,
                response.identified_product.name if response.identified_product else "<none>",
                (response.confidence or 0.0) * 100,
                catalog_row is not None,
            )
            # Clear the fake product - don't show it to user!
            response.identified_product = None
            response.needs_clarification = False  # Don't ask clarification, escalate!
            # Force escalation message - HUMAN STYLE (no AI mentions!)
            escalation_messages = [
                text_msg("Вітаю 🎀"),
                text_msg("Секундочку, уточню інформацію по цьому товару 🙌🏻"),
            ]

            # Send Telegram notification to manager in background (fire-and-forget)
            # This must NOT block the response to the customer!
            async def _send_notification_background():
                try:
                    from src.services.infra.notification_service import NotificationService

                    notification = NotificationService()
                    await notification.send_escalation_alert(
                        session_id=session_id or "unknown",
                        reason="Товар не знайдено в каталозі (можливо з іншого магазину)",
                        user_context=_normalize_text(user_message),
                        details={
                            "trace_id": trace_id,
                            "dialog_phase": "COMPLETED",
                            "current_state": State.STATE_7_END.value,
                            "intent": "PHOTO_IDENT",
                            "confidence": confidence * 100,
                            "image_url": deps.image_url if deps else None,
                        },
                    )
                    logger.info("📲 [SESSION %s] Telegram notification sent to manager", session_id)
                except Exception as notif_err:
                    logger.warning("Failed to send Telegram notification: %s", notif_err)

            # Fire and forget - don't await, just schedule
            task = asyncio.create_task(_send_notification_background())
            _BG_TASKS.add(task)
            task.add_done_callback(_BG_TASKS.discard)

            # Return IMMEDIATELY to customer - don't wait for notification
            return {
                "current_state": State.STATE_7_END.value,
                "messages": escalation_messages,
                "selected_products": [],
                "dialog_phase": "COMPLETED",
                "has_image": False,
                "escalation_level": "HARD",  # HARD escalation - manager MUST respond!
                "metadata": {
                    **state.get("metadata", {}),
                    "vision_confidence": response.confidence,
                    "needs_clarification": False,
                    "has_image": False,
                    "vision_greeted": True,
                    "vision_no_match_count": no_match_count,
                    "escalation_level": "HARD",
                    "escalation_reason": "product_not_in_catalog",
                },
                "agent_response": {
                    "messages": escalation_messages,
                    "metadata": {
                        "session_id": session_id,
                        "current_state": State.STATE_7_END.value,
                        "intent": "PHOTO_IDENT",
                        "escalation_level": "HARD",
                    },
                },
                "step_number": state.get("step_number", 0) + 1,
            }

    # =========================================================================
    # NORMAL FLOW
    # =========================================================================

    # Build response messages (Greeting -> Product -> Price -> Photo)
    vision_greeted = bool(metadata.get("vision_greeted"))
    response_messages = build_vision_messages(
        response=response,
        previous_messages=messages,
        vision_greeted=vision_greeted,
        user_message=user_message,
        catalog_product=catalog_row,
    )

    # Extract products for state
    selected_products = extract_products(response, state.get("selected_products", []))

    # Log metrics
    duration = time.perf_counter() - start_time
    track_metric("vision_node_duration", duration)
    log_agent_step(
        session_id=session_id,
        state=deps.current_state,
        intent="PHOTO_IDENT",
        event="vision_response",
        tool_results_count=len(selected_products),
        latency_ms=duration * 1000,
        extra={
            "identified": response.identified_product.name
            if response.identified_product
            else "None",
            "confidence": response.confidence,
        },
    )

    return {
        "current_state": State.STATE_2_VISION.value,
        "messages": response_messages,
        "selected_products": selected_products,
        "dialog_phase": "VISION_DONE",
        "has_image": True,
        "metadata": {
            **metadata,
            "vision_confidence": response.confidence,
            "needs_clarification": response.needs_clarification,
            "has_image": True,
            "vision_greeted": True,
            "vision_no_match_count": no_match_count,
        },
        "agent_response": {
            "messages": response_messages,
            "metadata": {
                "session_id": session_id,
                "current_state": State.STATE_2_VISION.value,
                "intent": "PHOTO_IDENT",
            },
        },
        "step_number": state.get("step_number", 0) + 1,
    }
