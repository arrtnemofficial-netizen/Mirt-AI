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
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.agents.pydantic.deps import create_deps_from_state
from src.core.state_machine import State
from src.services.core.observability import log_agent_step, log_trace, track_metric
from src.services.domain.vision.vision_ledger import (
    LEDGER_STATUS_BLOCKED,
    LEDGER_STATUS_ESCALATED,
    LEDGER_STATUS_FAILED,
    LEDGER_STATUS_PROCESSED,
    LEDGER_STATUS_PROCESSING,
    get_vision_ledger,
)

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

LEDGER_FINAL_STATUSES = {
    LEDGER_STATUS_PROCESSED,
    LEDGER_STATUS_ESCALATED,
    LEDGER_STATUS_BLOCKED,
}

async def run_vision(*args: Any, **kwargs: Any) -> Any:
    """
    Patch-friendly wrapper for the vision agent call.

    - Some tests patch `src.agents.langgraph.nodes.vision.run_vision` (package-level)
    - Others patch `src.agents.langgraph.nodes.vision.node.run_vision` (module-level)

    This wrapper ensures both patch targets work while still routing to the
    canonical implementation.
    """
    from src.agents.langgraph.nodes import vision as vision_pkg

    return await vision_pkg.run_vision(*args, **kwargs)

def _wrap_state_messages(agent_response_payload: dict[str, Any]) -> list[dict[str, str]]:
    """
    ConversationState.messages must be LangGraph-style: [{role, content}, ...].

    Vision builder produces multi-bubble payloads (text/image dicts). We keep those
    in `agent_response.messages`, but store a single assistant message containing
    the structured payload as string (same pattern as agent_node).
    """
    return [{"role": "assistant", "content": str(agent_response_payload)}]


def _get_vision_labels() -> dict[str, Any]:
    """Load vision labels from registry."""
    labels_json = get_snippet_by_header("VISION_LABELS")
    if not labels_json:
        return {}
    try:
        data = json.loads(labels_json[0])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _get_vision_node_templates() -> dict[str, Any]:
    """Load vision node templates from registry."""
    bubbles = get_snippet_by_header("VISION_NODE_TEMPLATES")
    if not bubbles:
        return {}
    try:
        data = json.loads(bubbles[0])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _compute_vision_hash(session_id: str | None, image_url: str | None) -> str | None:
    """Generate stable hash for session/image pair to guard against duplicates."""
    session = (session_id or "").strip()
    image = (image_url or "").strip()
    if not session or not image:
        return None
    normalized = f"{session}|{image}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _build_duplicate_messages(templates: dict[str, Any]) -> list[dict[str, Any]]:
    """Compose friendly duplicate-photo response bubbles."""
    duplicate_snippet = get_snippet_by_header("VISION_DUPLICATE_PHOTO")
    duplicate_body = (
        duplicate_snippet[0]
        if duplicate_snippet
        else templates.get(
            "duplicate_photo_body",
            "Ми вже проаналізували це фото й використовуємо попередній результат.",
        )
    )
    greeting = templates.get("duplicate_photo_greeting") or templates.get("escalation_greeting", "Привіт!")
    return [text_msg(greeting), text_msg(duplicate_body)]


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
    labels = _get_vision_labels()
    templates = _get_vision_node_templates()

    # Extract user message
    user_message = extract_user_message(messages) or labels.get(
        "vision_default_analysis_prompt",
        "Photo analysis",
    )

    # Build deps with image context
    deps = create_deps_from_state(state)
    deps.has_image = True
    deps.image_url = state.get("image_url") or state.get("metadata", {}).get("image_url")
    deps.current_state = State.STATE_2_VISION.value

    metadata = dict(state.get("metadata") or {})
    vision_hash = _compute_vision_hash(session_id, deps.image_url)
    ledger = get_vision_ledger()
    ledger_record = ledger.get_by_hash(vision_hash) if vision_hash else None
    ledger_metadata_base = {
        "session_id": session_id,
        "trace_id": trace_id,
        "current_state": State.STATE_2_VISION.value,
    }

    def _record_ledger_status(
        status: str,
        *,
        confidence: float | None = None,
        identified_product: Any | None = None,
        extra_metadata: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any] | None:
        if not vision_hash:
            return None
        meta_payload = {**ledger_metadata_base}
        if extra_metadata:
            meta_payload.update(extra_metadata)
        return ledger.record_result(
            session_id=session_id,
            image_hash=vision_hash,
            status=status,
            confidence=confidence,
            identified_product=identified_product,
            metadata=meta_payload,
            error_message=error_message,
        )

    if vision_hash and ledger_record is None:
        ledger_record = _record_ledger_status(
            LEDGER_STATUS_PROCESSING,
            extra_metadata={
                "stage": "start",
                "has_image": bool(deps.image_url),
            },
        )

    vision_result_id = ledger_record.get("vision_result_id") if ledger_record else None

    if ledger_record and ledger_record.get("status") in LEDGER_FINAL_STATUSES:
        duplicate_messages = _build_duplicate_messages(templates)
        duplicate_metadata = {
            **metadata,
            "vision_hash_processed": vision_hash,
            "vision_duplicate_detected": True,
            "has_image": True,
            "vision_result_id": ledger_record.get("vision_result_id"),
        }
        track_metric("vision_duplicate_photo", 1)
        log_agent_step(
            session_id=session_id,
            state=State.STATE_2_VISION.value,
            intent="PHOTO_IDENT",
            event="vision_duplicate",
            extra={"vision_hash": vision_hash, "vision_result_id": ledger_record.get("vision_result_id")},
        )
        if ledger_record.get("metadata"):
            duplicate_metadata["ledger_snapshot"] = ledger_record["metadata"]
        agent_response_payload = {
            "event": "vision_duplicate",
            "messages": duplicate_messages,
            "metadata": {
                "session_id": session_id,
                "current_state": State.STATE_2_VISION.value,
                "intent": "PHOTO_IDENT",
                "vision_duplicate_detected": True,
                "vision_result_id": ledger_record.get("vision_result_id"),
            },
        }
        return {
            "current_state": State.STATE_2_VISION.value,
            "messages": _wrap_state_messages(agent_response_payload),
            "selected_products": state.get("selected_products", []),
            "dialog_phase": "VISION_DONE",
            "has_image": True,
            "metadata": duplicate_metadata,
            "agent_response": agent_response_payload,
            "step_number": state.get("step_number", 0) + 1,
        }

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
        snippet = get_snippet_by_header("VISION_GREETING")
        if snippet:
            return snippet[0]
        return templates.get("escalation_greeting", "Hello")

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

        final_record = _record_ledger_status(
            LEDGER_STATUS_FAILED,
            error_message=error_msg[:200],
            extra_metadata={"stage": "vision_error_escalation"},
        )
        update = build_vision_error_escalation(error_msg, state.get("step_number", 0))
        # Ensure state messages are in {role, content} format for ConversationState contract.
        if isinstance(update.get("agent_response"), dict):
            update["messages"] = _wrap_state_messages(update["agent_response"])
        # Add session_id to metadata which might be missing in pure builder
        update["agent_response"]["metadata"]["session_id"] = session_id
        if final_record and final_record.get("vision_result_id"):
            update["metadata"]["vision_result_id"] = final_record["vision_result_id"]
            update["agent_response"]["metadata"]["vision_result_id"] = final_record["vision_result_id"]
        return update

    def _handle_missing_artifacts(missing: list[str]) -> dict[str, Any]:
        async def _send_notification_background() -> None:
            try:
                from src.services.infra.notification_service import NotificationService

                notification = NotificationService()
                reason_template = templates.get(
                    "artifacts_missing_reason",
                    "Vision artifacts missing: {missing}. Run data/vision/generate.py",
                )
                reason = reason_template.format(missing=", ".join(missing))
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

        final_record = _record_ledger_status(
            LEDGER_STATUS_BLOCKED,
            extra_metadata={"reason": "vision_artifacts_missing", "missing_artifacts": missing},
        )

        user_message_text = templates.get(
            "artifacts_missing_user",
            "This product is currently unavailable. We can suggest alternatives.",
        )
        escalation_messages = [
            text_msg(_get_greeting_bubble()),
            text_msg(user_message_text),
        ]

        result = {
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
        if final_record and final_record.get("vision_result_id"):
            result["metadata"]["vision_result_id"] = final_record["vision_result_id"]
            result["agent_response"]["metadata"]["vision_result_id"] = final_record["vision_result_id"]
        return result

    logger.info(
        "[SESSION %s] Vision node started: image=%s",
        session_id,
        deps.image_url[:60] if deps.image_url else "None",
    )

    try:
        # Call vision agent (goes through wrapper for test patching)
        response = await run_vision(message=user_message, deps=deps, message_history=None)
    except Exception as e:
        err = str(e)
        logger.error("Vision agent error: %s", err)
        _record_ledger_status(
            LEDGER_STATUS_FAILED,
            error_message=err[:200],
            extra_metadata={"stage": "vision_agent_error"},
        )
        return _handle_error_escalation(err)

    metadata = metadata
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
            retry_text = templates.get(
                "retry_low_quality",
                "Please send a clearer photo so we can match the model.",
            )
            retry_messages = [
                text_msg(_get_greeting_bubble()),
                text_msg(retry_text),
            ]
            return {
                "current_state": State.STATE_2_VISION.value,
                "messages": _wrap_state_messages(
                    {
                        "event": "vision_retry",
                        "messages": retry_messages,
                        "metadata": {
                            "session_id": session_id,
                            "current_state": State.STATE_2_VISION.value,
                            "intent": "PHOTO_IDENT",
                            "vision_result_id": vision_result_id,
                        },
                    }
                ),
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
                    "event": "vision_retry",
                    "messages": retry_messages,
                    "metadata": {
                        "session_id": session_id,
                        "current_state": State.STATE_2_VISION.value,
                        "intent": "PHOTO_IDENT",
                        "vision_result_id": vision_result_id,
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
            # Extract structured escalation reason from vision_quality_check if available
            escalation_reason = "low_confidence"
            escalation_context = {}
            if response.vision_quality_check:
                escalation_reason = response.vision_quality_check.get("escalation_reason", "low_confidence")
                escalation_context = {
                    "what_is_visible": response.vision_quality_check.get("what_is_visible"),
                    "what_is_missing": response.vision_quality_check.get("what_is_missing"),
                    "possible_confusion": response.vision_quality_check.get("possible_confusion", []),
                }
            elif product_not_in_catalog:
                escalation_reason = "product_not_in_catalog"
            elif no_product_identified:
                escalation_reason = "low_confidence"
            
            logger.warning(
                "[SESSION %s] ESCALATION: reason=%s confidence=%.0f%% catalog_found=%s",
                session_id,
                escalation_reason,
                (response.confidence or 0.0) * 100,
                catalog_row is not None,
            )
            # Clear the fake product - don't show it to user!
            response.identified_product = None
            response.needs_clarification = False  # Don't ask clarification, escalate!
            # Force escalation message - HUMAN STYLE (no AI mentions!)
            escalation_messages = [
                text_msg(templates.get("escalation_greeting", "Hello")),
                text_msg(templates.get("escalation_body", "Checking availability for this item.")),
            ]

            # Send Telegram notification to manager in background (fire-and-forget)
            # This must NOT block the response to the customer!
            async def _send_notification_background():
                try:
                    from src.services.infra.notification_service import NotificationService

                    notification = NotificationService()
                    reason_text = templates.get(
                        "escalation_reason_not_in_catalog",
                        f"Vision escalation: {escalation_reason}",
                    )
                    details = {
                        "trace_id": trace_id,
                        "dialog_phase": "COMPLETED",
                        "current_state": State.STATE_7_END.value,
                        "intent": "PHOTO_IDENT",
                        "confidence": confidence * 100,
                        "image_url": deps.image_url if deps else None,
                        "escalation_reason": escalation_reason,
                    }
                    if escalation_context:
                        details.update(escalation_context)
                    await notification.send_escalation_alert(
                        session_id=session_id or "unknown",
                        reason=reason_text,
                        user_context=_normalize_text(user_message),
                        details=details,
                    )
                    logger.info("📲 [SESSION %s] Telegram notification sent to manager", session_id)
                except Exception as notif_err:
                    logger.warning("Failed to send Telegram notification: %s", notif_err)

            # Fire and forget - don't await, just schedule
            task = asyncio.create_task(_send_notification_background())
            _BG_TASKS.add(task)
            task.add_done_callback(_BG_TASKS.discard)

            # Return IMMEDIATELY to customer - don't wait for notification
            agent_response_payload = {
                "event": "vision_escalation",
                "messages": escalation_messages,
                "metadata": {
                    "session_id": session_id,
                    "current_state": State.STATE_7_END.value,
                    "intent": "PHOTO_IDENT",
                    "escalation_level": "HARD",
                    "vision_result_id": vision_result_id,
                },
            }
            return {
                "current_state": State.STATE_7_END.value,
                "messages": _wrap_state_messages(agent_response_payload),
                "selected_products": [],
                "dialog_phase": "COMPLETED",
                "has_image": False,
                "escalation_level": "HARD",  # HARD escalation - manager MUST respond!
                "should_escalate": True,  # CRITICAL: Set flag for route_after_vision
                "escalation_reason": escalation_reason,  # CRITICAL: Set reason for escalation_node
                "metadata": {
                    **state.get("metadata", {}),
                    "vision_confidence": response.confidence,
                    "needs_clarification": False,
                    "has_image": False,
                    "vision_greeted": True,
                    "vision_no_match_count": no_match_count,
                    "escalation_level": "HARD",
                    "escalation_reason": escalation_reason,
                    "vision_quality_check": response.vision_quality_check,
                },
                "agent_response": agent_response_payload,
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

    # Record final success status
    final_record = _record_ledger_status(
        LEDGER_STATUS_PROCESSED,
        confidence=response.confidence,
        identified_product=response.identified_product,
        extra_metadata={"stage": "success"}
    )
    if final_record and final_record.get("vision_result_id"):
        vision_result_id = final_record["vision_result_id"]

    agent_response_payload = {
        "event": "vision_response",
        "messages": response_messages,
        "metadata": {
            "session_id": session_id,
            "current_state": State.STATE_2_VISION.value,
            "intent": "PHOTO_IDENT",
            "vision_result_id": vision_result_id,
        },
    }
    return {
        "current_state": State.STATE_2_VISION.value,
        "messages": _wrap_state_messages(agent_response_payload),
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
            "vision_result_id": vision_result_id,
            "vision_hash_processed": vision_hash,
        },
        "agent_response": agent_response_payload,
        "step_number": state.get("step_number", 0) + 1,
    }
