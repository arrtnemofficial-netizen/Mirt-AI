"""
Vision Node - Photo processing (Refactored).
============================================
Handles image identification and product matching.
Uses CartService for unified product management.
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
from src.services.cart import CartManager
from src.services.observability import log_agent_step, log_trace, track_metric

from .utils import (
    extract_height_from_text,
    get_size_and_price_for_height,
    text_msg,
)


if TYPE_CHECKING:
    from collections.abc import Callable
    from src.agents.pydantic.models import VisionResponse


logger = logging.getLogger(__name__)
_BG_TASKS: set[asyncio.Task] = set()
# Track active escalation tasks per session to prevent duplicates
_MAX_ACTIVE_ESCALATIONS = 1000
_ACTIVE_ESCALATIONS: set[str] = set()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

from .helpers.vision.escalation import (
    build_escalation_state_update,
    should_escalate_vision,
)
from .helpers.vision.product_enrichment import enrich_product_from_db as _enrich_product_from_db
from .helpers.vision.response_builder import build_vision_messages as _build_vision_messages


def _extract_products_with_service(
    response: VisionResponse,
    existing: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    is_product_addition: bool = False,
) -> list[dict[str, Any]]:
    """
    Extract products using CartManager.
    Unified logic for Vision and Agent.
    """
    confidence = response.confidence or 0.0

    # 1. Prepare candidates
    candidates = []
    if response.identified_product:
        candidates.append(response.identified_product.model_dump())
        logger.info(
            "[SESSION %s] Vision identified: '%s' (confidence=%.0f%%)",
            session_id or "?",
            response.identified_product.name,
            confidence * 100,
        )

    # 2. Add alternatives if low confidence
    from src.conf.config import settings
    alternatives_threshold = getattr(settings, "VISION_ALTERNATIVES_THRESHOLD", 0.85)

    if response.alternative_products and confidence < alternatives_threshold:
        candidates.extend([p.model_dump() for p in response.alternative_products])
        logger.info("Vision alternatives: %d (confidence < 85%%)", len(response.alternative_products))

    # 3. Use CartManager
    cart_manager = CartManager(session_id=session_id or "")

    if is_product_addition:
        # Add to existing (Strict check for addition)
        updated_cart, added = cart_manager.add_products(existing, candidates, strategy="strict")
        if added > 0:
            logger.info("[SESSION %s] Vision added %d products", session_id, added)
        else:
            logger.info("[SESSION %s] Vision: Duplicate product skipped", session_id)
        return updated_cart
    else:
        # Replace existing (Normal flow)
        # Note: In normal flow, we just return the candidates as the new cart
        return candidates


# =============================================================================
# MAIN NODE
# =============================================================================


async def vision_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """
    Process photo and identify product.
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    trace_id = state.get("trace_id", "")
    messages = state.get("messages", [])

    from .utils import extract_user_message
    user_message = extract_user_message(messages) or "Аналіз фото"

    # Build deps
    deps = create_deps_from_state(state)
    deps.has_image = True
    deps.image_url = state.get("image_url") or state.get("metadata", {}).get("image_url")

    metadata = state.get("metadata", {}) or {}
    is_product_addition = bool(metadata.get("product_addition_context", False))
    current_state_from_state = state.get("current_state", State.STATE_2_VISION.value)
    
    # Context handling
    if is_product_addition and current_state_from_state == State.STATE_5_PAYMENT_DELIVERY.value:
        deps.current_state = State.STATE_5_PAYMENT_DELIVERY.value
        logger.info("[SESSION %s] Vision called from STATE_5 (product addition)", session_id)
    else:
        deps.current_state = State.STATE_2_VISION.value

    # Error handling wrapper
    def _build_vision_error_escalation(error_msg: str) -> dict[str, Any]:
        escalation_messages = [
            text_msg("Не вдалося обробити фото. Передаю менеджеру."),
            text_msg("Будь ласка, очікуйте відповідь від менеджера."),
        ]
        session_key = f"{session_id}_vision_error"

        # Prevent duplicate escalations
        if session_key not in _ACTIVE_ESCALATIONS:
            if len(_ACTIVE_ESCALATIONS) >= _MAX_ACTIVE_ESCALATIONS:
                _ACTIVE_ESCALATIONS.discard(next(iter(_ACTIVE_ESCALATIONS)))
            _ACTIVE_ESCALATIONS.add(session_key)

            async def _notify():
                try:
                    from src.services.notifications import NotificationService
                    n = NotificationService()
                    await n.send_escalation_alert(
                        session_id=session_id or "unknown",
                        reason="vision_error",
                        user_context=user_message,
                        details={"error": error_msg[:200]},
                    )
                finally:
                    _ACTIVE_ESCALATIONS.discard(session_key)

            task = asyncio.create_task(_notify())
            _BG_TASKS.add(task)
            task.add_done_callback(_BG_TASKS.discard)

        return {
            "current_state": State.STATE_0_INIT.value,
            "messages": escalation_messages,
            "selected_products": [],
            "dialog_phase": "ESCALATED",
            "has_image": False,
            "escalation_level": "L2",
            "metadata": {
                **state.get("metadata", {}),
                "vision_error": error_msg[:200],
                "escalation_level": "L2",
            },
            "step_number": state.get("step_number", 0) + 1,
        }

    logger.info("🖼️ [SESSION %s] Vision node started", session_id)

    try:
        response = await run_vision(message=user_message, deps=deps)
    except Exception as e:
        logger.error("Vision agent error: %s", e)
        return _build_vision_error_escalation(str(e))

    # Enrichment logic
    catalog_row: dict[str, Any] | None = None
    confidence = response.confidence or 0.0
    claimed_name = getattr(response.identified_product, "name", None) if response.identified_product else None
    enrichment_failed = False

    if response.identified_product:
        # Cleanup color
        raw_color = response.identified_product.color
        if raw_color and ("/" in raw_color or " або " in raw_color.lower()):
            response.identified_product.color = ""
            raw_color = ""

        try:
            enriched = await _enrich_product_from_db(
                response.identified_product.name,
                color=raw_color
            )
            if enriched and isinstance(enriched.get("_catalog_row"), dict):
                catalog_row = enriched.get("_catalog_row")
                p = response.identified_product
                if p.price == 0: p.price = enriched.get("price", 0)
                if not p.photo_url: p.photo_url = enriched.get("photo_url", "")
                if not p.id: p.id = enriched.get("id", 0)
                if (not raw_color) and enriched.get("color"): p.color = enriched.get("color", "")
            else:
                enrichment_failed = True
                logger.warning("[SESSION %s] Enrichment FAILED for '%s'", session_id, response.identified_product.name)
                track_metric("vision_enrichment_failed", 1, {"session_id": session_id})
        except Exception as e:
            logger.warning("Enrichment error: %s", e)
            enrichment_failed = True

    # Escalation Check
    from src.conf.config import settings
    should_escalate, escalation_reason = should_escalate_vision(
        response, catalog_row, confidence_threshold=settings.VISION_CONFIDENCE_THRESHOLD
    )

    if should_escalate:
        # Build escalation logic...
        # Note: Using existing helper logic to keep behavior identical
        response.identified_product = None
        response.needs_clarification = False

        escalation_metadata = {
            "product_addition_context": is_product_addition,
            "existing_products_count": len(state.get("selected_products", [])) if is_product_addition else 0,
        }

        update = build_escalation_state_update(
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
        if "metadata" in update: update["metadata"].update(escalation_metadata)
        return update

    # Extract Products using CartManager
    existing_products = state.get("selected_products", []) if is_product_addition else []

    selected_products = _extract_products_with_service(
        response,
        existing_products,
        session_id=session_id,
        is_product_addition=is_product_addition,
    )

    # Build messages
    vision_greeted_before = bool(metadata.get("vision_greeted", False))
    assistant_messages = _build_vision_messages(
        response,
        messages,
        vision_greeted=vision_greeted_before,
        user_message=user_message,
        catalog_product=catalog_row,
        product_addition_context=is_product_addition,
        existing_products_count=len(existing_products) if is_product_addition else 0,
        enrichment_failed=enrichment_failed,
    )

    # Available colors logic
    available_colors = []
    if catalog_row:
        # Simplified extraction
        raw = catalog_row.get("_color_options") or catalog_row.get("colors") or catalog_row.get("color")
        if isinstance(raw, list): available_colors = [str(x) for x in raw]
        elif isinstance(raw, str): available_colors = [raw]

    # Height extraction (Simulated size assignment)
    height_in_text = extract_height_from_text(user_message)
    if response.identified_product and height_in_text:
        size_label, _ = get_size_and_price_for_height(height_in_text)
        response.identified_product.size = size_label
        if selected_products:
            selected_products[0]["size"] = size_label
            # Price update logic...
            if catalog_row:
                 with suppress(Exception):
                    selected_products[0]["price"] = CatalogService.get_price_for_size(catalog_row, size_label)

    # Metrics
    latency_ms = (time.perf_counter() - start_time) * 1000
    log_agent_step(session_id, State.STATE_2_VISION.value, "PHOTO_IDENT", "vision_complete", latency_ms)

    # Dialog Phase Transition
    next_phase = "VISION_DONE"
    next_state = State.STATE_2_VISION.value

    if is_product_addition and selected_products:
        next_phase = state.get("dialog_phase", "WAITING_FOR_PAYMENT_PROOF")
        next_state = State.STATE_5_PAYMENT_DELIVERY.value
    elif selected_products:
        if height_in_text:
            next_phase = "SIZE_COLOR_DONE"
            next_state = State.STATE_4_OFFER.value
        else:
            next_phase = "WAITING_FOR_SIZE"
            next_state = State.STATE_3_SIZE_COLOR.value
    elif response.needs_clarification:
         if confidence < settings.VISION_CONFIDENCE_THRESHOLD:
             next_phase = "ESCALATED"
             next_state = State.STATE_0_INIT.value
         else:
             next_phase = "VISION_DONE"
    else:
        next_phase = "ESCALATED"
        next_state = State.STATE_0_INIT.value

    # Escalation level
    escalation_level = "NONE"
    if not selected_products and (next_phase == "ESCALATED" or confidence < settings.VISION_CONFIDENCE_THRESHOLD):
        escalation_level = "L1"

    current_product_name = selected_products[0].get("name") if selected_products else None

    return {
        "current_state": next_state,
        "messages": assistant_messages,
        "selected_products": selected_products,
        "dialog_phase": next_phase,
        "has_image": False,
        "escalation_level": escalation_level,
        "metadata": {
            **state.get("metadata", {}),
            "vision_confidence": response.confidence,
            "needs_clarification": response.needs_clarification,
            "has_image": False,
            "vision_greeted": True,
            "available_colors": available_colors,
            "escalation_level": escalation_level,
            "current_product_name": current_product_name or state.get("metadata", {}).get("current_product_name"),
        },
        "agent_response": {
            "event": "simple_answer",
            "messages": [m for m in assistant_messages if m.get("type") in ("text", "image")],
            "products": selected_products,
        },
        "step_number": state.get("step_number", 0) + 1,
    }
