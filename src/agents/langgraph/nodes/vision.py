"""
Vision Node - Photo processing.
===============================
Handles image identification and product matching.
Uses run_vision directly (NOT through generic runner).

REFACTORED for clarity:
- _extract_products() - get products from VisionResponse
- _build_vision_messages() - build multi-bubble response
- vision_node() - main orchestrator (simple!)
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.vision_agent import run_vision
from src.core.state_machine import State
from src.services.catalog import CatalogService
from src.services.observability import log_agent_step, log_trace, track_metric

from .utils import (
    extract_height_from_text,
    get_size_and_price_for_height,
    image_msg,
    text_msg,
)


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents.pydantic.models import VisionResponse


logger = logging.getLogger(__name__)
_BG_TASKS: set[asyncio.Task] = set()
# Track active escalation tasks per session to prevent duplicates
# SAFETY: Limited size to prevent memory leak (FIFO eviction)
_MAX_ACTIVE_ESCALATIONS = 1000
_ACTIVE_ESCALATIONS: set[str] = set()


# =============================================================================
# HELPER FUNCTIONS (extracted for clarity)
# =============================================================================


# Import helper functions from vision helpers
from .helpers.vision.snippet_loader import (
    get_product_snippet as _get_product_snippet,
    get_snippet_by_header as _get_snippet_by_header,
)
from .helpers.vision.product_enrichment import enrich_product_from_db as _enrich_product_from_db
from .helpers.vision.escalation import (
    should_escalate_vision,
    build_escalation_state_update,
)


def _extract_products(
    response: VisionResponse,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract products from VisionResponse into state format.

    Logic:
    - If confidence >= 85% → show ONLY identified product (no alternatives)
    - If confidence < 85% → show identified + alternatives for user to choose
    """
    products = list(existing)
    confidence = response.confidence or 0.0

    if response.identified_product:
        products = [response.identified_product.model_dump()]
        logger.info(
            "Vision identified: %s (confidence=%.0f%%)",
            response.identified_product.name,
            confidence * 100,
        )

    # Only show alternatives if NOT confident enough
    # High confidence = we know what it is, no need to confuse user with options
    # Use configurable threshold (default 0.85 = 85%)
    from src.conf.config import settings
    alternatives_threshold = getattr(settings, "VISION_ALTERNATIVES_THRESHOLD", 0.85)
    if response.alternative_products and confidence < alternatives_threshold:
        products.extend([p.model_dump() for p in response.alternative_products])
        logger.info(
            "Vision alternatives: %d (showing because confidence < 85%%)",
            len(response.alternative_products),
        )
    elif response.alternative_products:
        logger.info(
            "Vision: skipping %d alternatives (confidence=%.0f%% >= 85%%)",
            len(response.alternative_products),
            confidence * 100,
        )

    return products


# Import response builder from helpers
from .helpers.vision.response_builder import build_vision_messages as _build_vision_messages


# =============================================================================
# MAIN NODE
# =============================================================================


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
    from .utils import extract_user_message

    user_message = extract_user_message(messages) or "Аналіз фото"

    # Build deps with image context
    deps = create_deps_from_state(state)
    deps.has_image = True
    deps.image_url = state.get("image_url") or state.get("metadata", {}).get("image_url")
    deps.current_state = State.STATE_2_VISION.value

    def _build_vision_error_escalation(error_msg: str) -> dict[str, Any]:
        escalation_messages = [
            text_msg("Не вдалося обробити фото. Передаю менеджеру."),
            text_msg("Будь ласка, очікуйте відповідь від менеджера."),
        ]

        # SAFETY: Prevent duplicate escalations for the same session
        session_key = f"{session_id}_vision_error"
        if session_key in _ACTIVE_ESCALATIONS:
            logger.warning(
                "🚨 [SESSION %s] Escalation already in progress, skipping duplicate",
                session_id,
            )
        else:
            # SAFETY: Prevent memory leak by limiting set size (FIFO eviction)
            if len(_ACTIVE_ESCALATIONS) >= _MAX_ACTIVE_ESCALATIONS:
                oldest = next(iter(_ACTIVE_ESCALATIONS), None)
                if oldest:
                    _ACTIVE_ESCALATIONS.discard(oldest)
                    logger.warning(
                        "Active escalations set full (%d), evicted oldest: %s",
                        _MAX_ACTIVE_ESCALATIONS,
                        oldest,
                    )
            _ACTIVE_ESCALATIONS.add(session_key)

        async def _send_notification_background() -> None:
            try:
                from src.services.notifications import NotificationService

                notification = NotificationService()
                await notification.send_escalation_alert(
                    session_id=session_id or "unknown",
                    reason="vision_error",
                    user_context=user_message,
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
            finally:
                # Remove from active escalations after completion
                _ACTIVE_ESCALATIONS.discard(session_key)

        task = asyncio.create_task(_send_notification_background())
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)

        return {
            "current_state": State.STATE_0_INIT.value,
            "messages": escalation_messages,
            "selected_products": [],
            "dialog_phase": "ESCALATED",
            "has_image": False,
            "image_url": None,
            "escalation_level": "L2",  # HARD escalation → L2 (contract-compliant)
            "metadata": {
                **state.get("metadata", {}),
                "vision_error": error_msg[:200],
                "needs_clarification": False,
                "has_image": False,
                "escalation_level": "L2",  # HARD → L2
                "escalation_reason": "vision_error",
                "escalation_mode": "HARD",  # UX mode (soft/hard) stored separately
            },
            "agent_response": {
                "messages": escalation_messages,
                "metadata": {
                    "session_id": session_id,
                    "current_state": State.STATE_0_INIT.value,
                    "intent": "PHOTO_IDENT",
                    "escalation_level": "L2",  # HARD → L2
                    "notes": "escalation_mode=HARD",  # UX mode in notes
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
        return _build_vision_error_escalation(err)

    # -------------------------------------------------------------------------
    # Catalog enrichment (best-effort): only possible if Vision gave a candidate
    # -------------------------------------------------------------------------
    catalog_row: dict[str, Any] | None = None
    confidence = response.confidence or 0.0
    claimed_name = (
        getattr(response.identified_product, "name", None) if response.identified_product else None
    )
    enrichment_failed = False  # Track if enrichment failed (product not in catalog)

    if response.identified_product:
        # Handle ambiguous colors (e.g., "рожевий / червоний")
        vision_color_raw = response.identified_product.color
        vision_color = vision_color_raw
        try:
            if vision_color_raw and (
                "/" in vision_color_raw or " або " in vision_color_raw.lower()
            ):
                vision_color = ""
                response.identified_product.color = ""
        except Exception:
            vision_color = vision_color_raw

        # Attempt enrichment
        try:
            enriched_row = await _enrich_product_from_db(
                response.identified_product.name,
                color=vision_color,
            )
            if enriched_row and isinstance(enriched_row.get("_catalog_row"), dict):
                catalog_row = enriched_row.get("_catalog_row")
                # Update product with enriched data
                if response.identified_product.price == 0:
                    response.identified_product.price = enriched_row.get("price", 0)
                if not response.identified_product.photo_url:
                    response.identified_product.photo_url = enriched_row.get("photo_url", "")
                if not response.identified_product.id:
                    response.identified_product.id = enriched_row.get("id", 0)
                if (not vision_color) and enriched_row.get("color"):
                    response.identified_product.color = enriched_row.get("color", "")
                # Store color options and ambiguous flag
                try:
                    if isinstance(enriched_row.get("_color_options"), list):
                        catalog_row["_color_options"] = enriched_row.get("_color_options")
                    if "_ambiguous_color" in enriched_row:
                        catalog_row["_ambiguous_color"] = enriched_row.get("_ambiguous_color")
                except Exception:
                    pass
            else:
                # Enrichment FAILED - product not found in DB
                # This is a critical quality issue: escalate instead of clarification
                enrichment_failed = True
                logger.warning(
                    "🚨 [SESSION %s] Enrichment FAILED for '%s' - product not in catalog. "
                    "Will escalate to manager.",
                    session_id,
                    response.identified_product.name,
                )
                track_metric(
                    "vision_enrichment_failed",
                    1,
                    {
                        "session_id": session_id,
                        "product_name": response.identified_product.name,
                        "confidence": confidence * 100,
                    },
                )
                # Keep product info for escalation check, but mark that it's not in catalog
                # (catalog_row remains None, which will trigger escalation)
        except Exception as enrich_err:
            logger.warning("Enrichment error: %s", enrich_err)
            catalog_row = None
            # If we had a product but enrichment failed, mark as failed
            if response.identified_product:
                enrichment_failed = True

    # =====================================================
    # DUAL-TRACK ESCALATION (SSOT)
    # =====================================================
    # ESCALATE if:
    # 1) Vision "identified" product but it's NOT in our catalog (hallucination/competitor)
    # 2) Vision couldn't identify anything AND confidence is low
    #
    # IMPORTANT: This must work even when identified_product is None.
    # Otherwise UX regresses to "що саме на фото?" (which user explicitly rejected).
    # =====================================================
    from src.conf.config import settings

    should_escalate, escalation_reason = should_escalate_vision(
        response,
        catalog_row,
        confidence_threshold=settings.VISION_CONFIDENCE_THRESHOLD,
    )

    if should_escalate:
        logger.warning(
            "🚨 [SESSION %s] ESCALATION: %s! claimed='%s' confidence=%.0f%% catalog_found=%s enrichment_failed=%s",
            session_id,
            escalation_reason,
            claimed_name or "<none>",
            confidence * 100,
            catalog_row is not None,
            enrichment_failed,
        )
        # Do NOT show incomplete/foreign product to customer
        response.identified_product = None
        response.needs_clarification = False  # Escalation, not clarification

        # Build escalation state update with dual-track notification
        return build_escalation_state_update(
            state=state,
            session_id=session_id,
            trace_id=trace_id,
            user_message=user_message,
            image_url=deps.image_url,
            escalation_reason=escalation_reason,
            confidence=confidence,
            claimed_name=claimed_name,
            create_task_fn=asyncio.create_task,
            active_escalations=_ACTIVE_ESCALATIONS,
            bg_tasks=_BG_TASKS,
        )

    # Log response with clear visibility
    product_name = (
        response.identified_product.name if response.identified_product else "<not identified>"
    )
    product_price = response.identified_product.price if response.identified_product else 0
    logger.info(
        "🖼️ [SESSION %s] Vision RESULT: product='%s' price=%s confidence=%.0f%%",
        session_id,
        product_name,
        product_price,
        response.confidence * 100,
    )

    # Async trace logging (disabled by default via AsyncTracingService flag)
    try:
        await log_trace(
            session_id=session_id or "",
            trace_id=f"vision:{session_id}:{int(start_time * 1000)}",
            node_name="vision_node",
            state_name=State.STATE_2_VISION.value,
            prompt_key="vision_main",
            input_snapshot={
                "message": user_message,
                "image_url": deps.image_url,
            },
            output_snapshot={
                "product_name": product_name,
                "price": product_price,
                "confidence": response.confidence,
            },
            latency_ms=(time.perf_counter() - start_time) * 1000,
            model_name=None,
        )
    except Exception as trace_error:  # Observability must not break main flow
        logger.debug("Vision trace logging skipped: %s", trace_error)

    # Extract products and build messages using helpers
    selected_products = _extract_products(response, state.get("selected_products", []))

    metadata = state.get("metadata", {})
    vision_greeted_before = bool(metadata.get("vision_greeted", False))
    assistant_messages = _build_vision_messages(
        response,
        messages,
        vision_greeted=vision_greeted_before,
        user_message=user_message,  # Передаємо текст для витягування зросту!
        catalog_product=catalog_row,
    )

    available_colors: list[str] = []
    try:
        if isinstance(catalog_row, dict):
            if isinstance(catalog_row.get("_color_options"), list):
                available_colors = [
                    str(x).strip()
                    for x in (catalog_row.get("_color_options") or [])
                    if str(x).strip()
                ]
            elif isinstance(catalog_row.get("colors"), list):
                available_colors = [
                    str(x).strip() for x in (catalog_row.get("colors") or []) if str(x).strip()
                ]
            elif isinstance(catalog_row.get("colors"), str):
                s = str(catalog_row.get("colors") or "").strip()
                if s:
                    available_colors = [s]
            elif isinstance(catalog_row.get("color"), str):
                s = str(catalog_row.get("color") or "").strip()
                if s:
                    available_colors = [s]
    except Exception:
        available_colors = []

    height_in_text = extract_height_from_text(user_message)
    if response.identified_product and height_in_text:
        size_label, _ = get_size_and_price_for_height(height_in_text)
        response.identified_product.size = size_label
        if catalog_row:
            with suppress(Exception):
                response.identified_product.price = CatalogService.get_price_for_size(
                    catalog_row,
                    size_label,
                )

        if selected_products:
            first = dict(selected_products[0])
            first["size"] = size_label
            if catalog_row:
                with suppress(Exception):
                    first["price"] = CatalogService.get_price_for_size(catalog_row, size_label)
                if not first.get("photo_url"):
                    first["photo_url"] = (
                        catalog_row.get("photo_url")
                        or catalog_row.get("image_url")
                        or catalog_row.get("photo")
                        or catalog_row.get("image")
                        or first.get("photo_url")
                        or ""
                    )
                if not first.get("id"):
                    first["id"] = catalog_row.get("id") or first.get("id")
            selected_products[0] = first

    # Metrics
    latency_ms = (time.perf_counter() - start_time) * 1000
    log_agent_step(
        session_id=session_id,
        state=State.STATE_2_VISION.value,
        intent="PHOTO_IDENT",
        event="vision_complete",
        latency_ms=latency_ms,
        extra={
            "trace_id": trace_id,
            "products_count": len(selected_products),
            "confidence": response.confidence,
        },
    )
    track_metric("vision_node_latency_ms", latency_ms)

    # =====================================================
    # DIALOG PHASE (Turn-Based State Machine)
    # =====================================================
    # Визначаємо наступну фазу на основі результату Vision:
    #
    # 1. Товар впізнано → WAITING_FOR_SIZE (STATE_3)
    #    - Вже показали товар, питаємо зріст
    #    - Наступне повідомлення юзера йде в agent
    #
    # 2. Товар НЕ впізнано → VISION_DONE
    #    - Потрібно уточнення від юзера
    #
    # 3. needs_clarification → VISION_DONE
    #    - Vision не впевнений, питає уточнення
    # =====================================================
    if selected_products:
        if height_in_text:
            # Зріст вже є - готові до оформлення!
            next_phase = "SIZE_COLOR_DONE"
            next_state = State.STATE_4_OFFER.value
        else:
            # Тільки фото - чекаємо зріст
            next_phase = "WAITING_FOR_SIZE"
            next_state = State.STATE_3_SIZE_COLOR.value
    elif response.needs_clarification:
        # SAFETY: If confidence is low, escalate even if needs_clarification=True
        # User already sent photo - asking again is poor UX
        if confidence < settings.VISION_CONFIDENCE_THRESHOLD:
            next_phase = "ESCALATED"
            next_state = State.STATE_0_INIT.value
            logger.info(
                "🚨 [SESSION %s] Escalating despite needs_clarification: low confidence (%.0f%%)",
                session_id,
                confidence * 100,
            )
        else:
            next_phase = "VISION_DONE"
            next_state = State.STATE_2_VISION.value
    else:
        # Unknown product - escalate to manager!
        next_phase = "ESCALATED"
        next_state = State.STATE_0_INIT.value

    # Determine escalation level
    escalation_level = "NONE"
    if not selected_products:
        # Product not identified → escalate (even if needs_clarification, if confidence is low)
        if next_phase == "ESCALATED" or (not response.needs_clarification) or (confidence < settings.VISION_CONFIDENCE_THRESHOLD):
            escalation_level = "L1"  # SOFT escalation → L1 (contract-compliant)

    return {
        "current_state": next_state,
        "messages": assistant_messages,
        "selected_products": selected_products,
        "dialog_phase": next_phase,
        # ВАЖЛИВО: Скидаємо has_image після обробки!
        # Це запобігає повторному входу в vision при наступних текстових повідомленнях
        "has_image": False,
        "escalation_level": escalation_level,  # For CRM tracking
        "metadata": {
            **state.get("metadata", {}),
            "vision_confidence": response.confidence,
            "needs_clarification": response.needs_clarification,
            "has_image": False,  # Також в metadata
            "vision_greeted": True,  # greeting уже відправлено
            "available_colors": available_colors,
            "escalation_level": escalation_level,
        },
        # Lightweight agent_response so renderers (Telegram/ManyChat) можуть показати фото/текст
        "agent_response": {
            "event": "simple_answer",
            "messages": [
                {"type": str(m.get("type") or "text"), "content": str(m.get("content") or "")}
                for m in assistant_messages
                if str(m.get("type") or "text") in ("text", "image")
            ],
            "products": selected_products,
            "metadata": {
                "session_id": session_id,
                "current_state": next_state,
                "intent": "PHOTO_IDENT",
                "escalation_level": escalation_level,
            },
        },
        "step_number": state.get("step_number", 0) + 1,
        "last_error": None,
    }
