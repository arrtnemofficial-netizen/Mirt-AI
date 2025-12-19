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
from src.services.catalog_service import CatalogService
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


# =============================================================================
# HELPER FUNCTIONS (extracted for clarity)
# =============================================================================


def _get_snippet_by_header(header_name: str) -> list[str] | None:
    """Get snippet by exact header name from snippets.md.

    Returns list of bubbles (split by ---) or None if not found.
    """
    try:
        from src.core.prompt_registry import registry

        content = registry.get("system.snippets").content
    except Exception:
        return None

    if not content:
        return None

    # Parse snippets.md - find section with exact header
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for ### header with exact match
        if line.startswith("### ") and line[4:].strip() == header_name:
            # Found exact match! Extract the snippet body
            body_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("### "):
                body_lines.append(lines[i])
                i += 1

            # Parse body: skip КОЛИ/НЕ КОЛИ lines, split by ---
            text_lines = []
            for bl in body_lines:
                bl_stripped = bl.strip()
                if bl_stripped.startswith("КОЛИ:") or bl_stripped.startswith("НЕ КОЛИ:"):
                    continue
                text_lines.append(bl_stripped)

            # Join and split by ---
            full_text = "\n".join(text_lines).strip()
            if not full_text:
                return None

            bubbles = [b.strip() for b in full_text.split("---") if b.strip()]
            if bubbles:
                logger.info("📋 Found snippet '%s': %d bubbles", header_name, len(bubbles))
                return bubbles
            return None
        i += 1

    return None


def _get_product_snippet(product_name: str) -> list[str] | None:
    """Get presentation snippet for a product from snippets.md.

    Returns list of bubbles (split by ---) or None if not found.
    Universal: works for ANY product that has a snippet in snippets.md.

    Format in snippets.md:
        ### Сукня Анна — преміум-презентація
        КОЛИ: ...
        Текст бабла 1
        ---
        Текст бабла 2
    """
    try:
        from src.core.prompt_registry import registry

        content = registry.get("system.snippets").content
    except Exception:
        return None

    if not content:
        return None

    # Normalize product name for matching
    pn_lower = (product_name or "").lower().strip()
    if not pn_lower:
        return None

    # Extract key words (e.g., "сукня анна" -> ["сукня", "анна"])
    keywords = [w for w in pn_lower.split() if len(w) > 2]
    if not keywords:
        return None

    # Parse snippets.md - find sections matching product
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for ### headers that contain product keywords
        if line.startswith("### "):
            header_lower = line[4:].lower()

            # Check if this header matches our product (all keywords present)
            if all(kw in header_lower for kw in keywords):
                # Found a match! Look for "презентація" or first snippet for this product
                if "презентація" in header_lower or "відповідь" in header_lower:
                    # Extract the snippet body (until next ### or EOF)
                    body_lines = []
                    i += 1
                    while i < len(lines) and not lines[i].startswith("### "):
                        body_lines.append(lines[i])
                        i += 1

                    # Parse body: skip КОЛИ/НЕ КОЛИ lines, split by ---
                    text_lines = []
                    for bl in body_lines:
                        bl_stripped = bl.strip()
                        if (
                            bl_stripped.startswith("КОЛИ:")
                            or bl_stripped.startswith("НЕ КОЛИ:")
                            or bl_stripped.startswith("ПРІОРИТЕТ:")
                        ):
                            continue
                        text_lines.append(bl_stripped)

                    # Join and split by ---
                    full_text = "\n".join(text_lines).strip()
                    if not full_text:
                        return None

                    bubbles = [b.strip() for b in full_text.split("---") if b.strip()]
                    if bubbles:
                        logger.info(
                            "📋 Found snippet for '%s': %d bubbles", product_name, len(bubbles)
                        )
                        return bubbles
                    return None
        i += 1

    return None


async def _enrich_product_from_db(
    product_name: str, color: str | None = None
) -> dict[str, Any] | None:
    """Lookup product in DB by name (and color if provided) and return enriched data.

    Використовується, коли Vision повернув назву без ціни/фото.
    ВАЖЛИВО: Якщо є колір - шукає з кольором для точного match!
    """
    try:
        catalog = CatalogService()

        def _norm(s: str) -> str:
            return " ".join((s or "").lower().strip().split())

        def _base_name(s: str) -> str:
            s = (s or "").strip()
            if "(" in s:
                return s.split("(")[0].strip()
            return s

        # Якщо колір вже в назві (наприклад "Костюм Ритм (рожевий)") - не дублюємо
        search_query = product_name
        if (
            color
            and f"({color})" not in product_name.lower()
            and color.lower() not in product_name.lower()
        ):
            # Спробуємо знайти точний match з кольором
            search_query = f"{product_name} ({color})"

        results = await catalog.search_products(query=search_query, limit=5)

        if not results:
            all_rows = await catalog.get_products_for_vision()
            target = _norm(product_name)
            target_base = _norm(_base_name(product_name))
            color_norm = _norm(color or "")

            scored: list[tuple[int, dict[str, Any]]] = []
            for row in all_rows or []:
                name = str(row.get("name") or "")
                n = _norm(name)
                nb = _norm(_base_name(name))
                score = 0
                if n == target or nb == target_base:
                    score += 50
                if target and (target in n or n in target):
                    score += 15
                if target_base and (target_base in nb or nb in target_base):
                    score += 10
                if color_norm and color_norm in n:
                    score += 5
                if score > 0:
                    scored.append((score, row))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = [row for _score, row in scored[:5]]

        # Якщо не знайшли з повною назвою - спробуємо базову назву без кольору
        if not results and "(" in product_name:
            base_name = product_name.split("(")[0].strip()
            logger.debug("Retry search with base name: '%s'", base_name)
            results = await catalog.search_products(query=base_name, limit=5)

        # Якщо є колір - шукаємо товар з цим кольором
        product = None
        if color and results:
            for p in results:
                p_name = p.get("name", "").lower()
                if color.lower() in p_name:
                    product = p
                    break

        def _extract_colors(row: dict[str, Any]) -> list[str]:
            raw = row.get("colors") or row.get("color") or []
            if isinstance(raw, list):
                return [str(x).strip() for x in raw if str(x).strip()]
            if isinstance(raw, str):
                return [raw.strip()] if raw.strip() else []
            return []

        color_options: list[str] = []
        if results:
            seen: set[str] = set()
            for r in results:
                for c in _extract_colors(r):
                    lc = c.lower()
                    if lc not in seen:
                        seen.add(lc)
                        color_options.append(c)

        # Якщо не знайшли з кольором - беремо перший
        if not product and results:
            product = results[0]

        if product:
            price_display = CatalogService.format_price_display(product)
            # Try multiple possible column names for photo URL
            photo_url = (
                product.get("photo_url")
                or product.get("image_url")
                or product.get("photo")
                or product.get("image")
                or ""
            )

            ambiguous_color = bool((not color) and len(color_options) >= 2)
            if ambiguous_color:
                photo_url = ""
                with suppress(Exception):
                    product["_color_options"] = color_options

            logger.info(
                "📦 Enriched from DB: %s (color=%s) -> %s, photo=%s",
                product_name,
                color,
                price_display,
                photo_url[:50] if photo_url else "<no photo>",
            )
            return {
                "id": product.get("id", 0),
                "name": product.get("name", product_name),
                "price": CatalogService.get_price_for_size(product),
                "price_display": price_display,
                "color": ""
                if ambiguous_color
                else (
                    (product.get("colors") or [""])[0]
                    if isinstance(product.get("colors"), list)
                    else product.get("colors", "")
                ),
                "photo_url": photo_url,
                "description": product.get("description", ""),
                "_catalog_row": product,
                "_color_options": color_options,
                "_ambiguous_color": ambiguous_color,
            }
    except Exception as e:
        logger.warning("DB enrichment failed: %s", e)
    return None


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
    if response.alternative_products and confidence < 0.85:
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


def _build_vision_messages(
    response: VisionResponse,
    previous_messages: list[Any],
    vision_greeted: bool,
    user_message: str = "",
    catalog_product: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """
    Build multi-bubble assistant response from VisionResponse.

    Message order (if product found):
    1. Greeting (if first message): без згадки про фото/бота
    2. Product: назва + колір
    3. Ціна (якщо зріст вже вказано) АБО запит про зріст
    4. Photo: [product image]

    If product NOT found:
    - Clarification question from LLM or fallback
    """
    messages: list[dict[str, str]] = []
    confidence = response.confidence or 0.0

    def _history_has_greeting(prev: list[Any]) -> bool:
        try:
            for m in prev or []:
                if isinstance(m, dict):
                    content = str(m.get("content") or "")
                    if "менеджер соф" in content.lower():
                        return True
        except Exception:
            return False
        return False

    def _norm_color(s: str) -> str:
        return " ".join((s or "").lower().strip().split())

    def _is_ambiguous_color(s: str) -> bool:
        ss = _norm_color(s)
        return ("/" in ss) or (" або " in ss)

    # 1. Greeting: один раз на першу фото-взаємодію в сесії
    if (not vision_greeted) or (not _history_has_greeting(previous_messages)):
        messages.append(text_msg("Вітаю 🎀 З вами MIRT_UA, менеджер Софія."))

    # 2. Product highlight БЕЗ ЦІНИ (ціна тільки після зросту!)
    # НЕ використовуємо reply_to_user від LLM - будуємо відповідь самі з точними даними з БД
    product = response.identified_product
    if product:
        # БАБЛА 2: Назва товару + колір (БЕЗ ЦІНИ!)
        # Ціна буде показана тільки після того як клієнт вкаже зріст
        product_name = product.name

        # Check if color is already in the name (e.g., "Костюм Ритм (рожевий)")
        # to avoid duplication like "Костюм Ритм (рожевий) у кольорі рожевий"
        color_already_in_name = product.color and product.color.lower() in product_name.lower()

        prefix = "Це наш"
        if confidence < 0.5:
            prefix = "Схоже, це наш"

        color_options: list[str] = []
        try:
            if catalog_product and isinstance(catalog_product.get("_color_options"), list):
                color_options = [
                    str(x) for x in (catalog_product.get("_color_options") or []) if str(x).strip()
                ]
        except Exception:
            color_options = []

        option_norms = {_norm_color(c) for c in color_options}
        needs_color_confirmation = bool(
            (len(color_options) >= 2)
            and (
                (not product.color)
                or _is_ambiguous_color(product.color)
                or (option_norms and (_norm_color(product.color) not in option_norms))
            )
        )

        if color_already_in_name:
            # Color is in name - just use the name
            message_text = f"{prefix} {product_name} 💛"
        elif product.color and (not needs_color_confirmation):
            # Color NOT in name - add it
            message_text = f"{prefix} {product_name} у кольорі {product.color} 💛"
        else:
            # No color info at all
            message_text = f"{prefix} {product_name} 💛"

        messages.append(text_msg(message_text))

        # Try to get beautiful snippet from snippets.md for this product
        # Universal: works for Сукня Анна, Костюм Лагуна, or ANY product you add to snippets.md
        snippet_bubbles = _get_product_snippet(product_name)
        if snippet_bubbles:
            # Use snippet instead of generic description
            for bubble in snippet_bubbles[:3]:  # Max 3 bubbles for presentation
                messages.append(text_msg(bubble))
        elif catalog_product:
            description = str(catalog_product.get("description") or "").strip()
            if description:
                description = " ".join(description.split())
                first_line = description.split("\n", 1)[0].strip()
                snippet_src = first_line or description

                sentences: list[str] = []
                buf = snippet_src
                for sep in (".", "!", "?"):
                    if sep in buf:
                        parts = [p.strip() for p in buf.split(sep) if p.strip()]
                        if parts:
                            sentences = parts
                            break

                if sentences:
                    snippet = ". ".join(sentences[:2]).strip() + "."
                else:
                    snippet = snippet_src[:180].rstrip()

                if snippet:
                    messages.append(text_msg(snippet))

        # Photo bubble should come before the question bubble (ManyChat/IG UX).
        if product.photo_url and (not needs_color_confirmation):
            messages.append(image_msg(product.photo_url))

        if needs_color_confirmation:
            options_text = ", ".join(color_options[:5])
            messages.append(
                text_msg(f"Підкажіть, будь ласка, який колір обираєте: {options_text}? 🤍")
            )

        # БАБЛА 3: Якщо зріст вже в тексті (фото + текст разом) - показуємо ціну одразу!
        # Інакше питаємо зріст, і agent_node обробить відповідь
        height = extract_height_from_text(user_message)
        if height:
            # Зріст є в тексті разом з фото - показуємо ціну одразу!
            size_label, price = get_size_and_price_for_height(height)
            if catalog_product:
                with suppress(Exception):
                    price = int(CatalogService.get_price_for_size(catalog_product, size_label))
            messages.append(text_msg(f"На {height} см підійде розмір {size_label}"))
            messages.append(text_msg(f"Ціна {price} грн"))
            messages.append(text_msg("Оформлюємо? 🌸"))
        else:
            # Тільки фото без зросту - питаємо
            messages.append(text_msg("На який зріст підказати? 🌸"))

    # 4. Clarification (тільки якщо НЕ впізнали товар)
    elif response.clarification_question:
        messages.append(text_msg(response.clarification_question.strip()))
    elif response.needs_clarification:
        messages.append(
            text_msg("Не можу точно визначити модель. Підкажіть, будь ласка, що це за товар? 🤍")
        )

    # If we still have no product and no clarification - this is likely NOT our product
    # Use "Невідомий товар" snippet from snippets.md
    if (
        (not response.identified_product)
        and (not response.clarification_question)
        and (not response.needs_clarification)
    ):
        # Try to get snippet for unknown product
        unknown_snippet = _get_snippet_by_header("Невідомий товар (ескалація)")
        if unknown_snippet:
            for bubble in unknown_snippet[:3]:  # Max 3 bubbles
                messages.append(text_msg(bubble))
        else:
            # Fallback if snippet not found
            messages.append(text_msg("Це не наша модель 🤍"))
            messages.append(text_msg("Але стиль дуже схожий на наші костюми/сукні!"))
            messages.append(
                text_msg("Показати наші варіанти? Підкажіть, що шукаєте і на який зріст 🌸")
            )

    # 5. Fallback - use "Помилка розпізнавання фото" snippet
    if not messages:
        error_snippet = _get_snippet_by_header("Помилка розпізнавання фото")
        if error_snippet:
            for bubble in error_snippet:
                messages.append(text_msg(bubble))
        else:
            messages.append(text_msg("Не впізнала модель на фото 🤍"))
            messages.append(text_msg("Передаю менеджеру, щоб допоміг вам особисто!"))

    return messages


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

        async def _send_notification_background() -> None:
            try:
                from src.services.notification_service import NotificationService

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
            "escalation_level": "HARD",
            "metadata": {
                **state.get("metadata", {}),
                "vision_error": error_msg[:200],
                "needs_clarification": False,
                "has_image": False,
                "escalation_level": "HARD",
                "escalation_reason": "vision_error",
            },
            "agent_response": {
                "messages": escalation_messages,
                "metadata": {
                    "session_id": session_id,
                    "current_state": State.STATE_0_INIT.value,
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
        return _build_vision_error_escalation(err)

    catalog_row: dict[str, Any] | None = None
    if response.identified_product:
        try:
            enriched_row = await _enrich_product_from_db(
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

        # Case 1: AI "identified" product but it's NOT in catalog (hallucination/competitor)
        product_not_in_catalog = response.identified_product is not None and catalog_row is None

        # Case 2: AI couldn't identify anything (product is None or "<not identified>")
        no_product_identified = response.identified_product is None or (
            response.identified_product
            and response.identified_product.name in ("<not identified>", "<none>", "")
        )

        # Case 3: Low confidence - don't trust the result
        low_confidence = confidence < 0.5

        # ESCALATE if: not in catalog OR (no product AND low confidence)
        should_escalate = product_not_in_catalog or (no_product_identified and low_confidence)

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
                    from src.services.notification_service import NotificationService

                    notification = NotificationService()
                    await notification.send_escalation_alert(
                        session_id=session_id or "unknown",
                        reason="Товар не знайдено в каталозі (можливо з іншого магазину)",
                        user_context=user_message,
                        details={
                            "trace_id": trace_id,
                            "dialog_phase": "ESCALATED",
                            "current_state": State.STATE_0_INIT.value,
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
                "current_state": State.STATE_0_INIT.value,
                "messages": escalation_messages,
                "selected_products": [],
                "dialog_phase": "ESCALATED",
                "has_image": False,
                "escalation_level": "HARD",  # HARD escalation - manager MUST respond!
                "metadata": {
                    **state.get("metadata", {}),
                    "vision_confidence": response.confidence,
                    "needs_clarification": False,
                    "has_image": False,
                    "vision_greeted": True,
                    "escalation_level": "HARD",
                    "escalation_reason": "product_not_in_catalog",
                },
                "agent_response": {
                    "messages": escalation_messages,
                    "metadata": {
                        "session_id": session_id,
                        "current_state": State.STATE_0_INIT.value,
                        "intent": "PHOTO_IDENT",
                        "escalation_level": "HARD",
                    },
                },
                "step_number": state.get("step_number", 0) + 1,
            }

        # Enrich product from DB if Vision returned partial data (missing id/photo/price)
        if response.identified_product and (
            response.identified_product.price == 0
            or not response.identified_product.photo_url
            or not response.identified_product.id
        ):
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
            enriched = await _enrich_product_from_db(
                response.identified_product.name,
                color=vision_color,
            )
            if enriched:
                if response.identified_product.price == 0:
                    response.identified_product.price = enriched.get("price", 0)
                if not response.identified_product.photo_url:
                    response.identified_product.photo_url = enriched.get("photo_url", "")
                if not response.identified_product.id:
                    response.identified_product.id = enriched.get("id", 0)
                if (not vision_color) and enriched.get("color"):
                    response.identified_product.color = enriched.get("color", "")
                if (not catalog_row) and isinstance(enriched.get("_catalog_row"), dict):
                    catalog_row = enriched.get("_catalog_row")
                if catalog_row and isinstance(catalog_row, dict):
                    if isinstance(enriched.get("_color_options"), list):
                        catalog_row["_color_options"] = enriched.get("_color_options")
                    if "_ambiguous_color" in enriched:
                        catalog_row["_ambiguous_color"] = enriched.get("_ambiguous_color")

                # НЕ генеруємо reply з ціною тут!
                # Ціна залежить від розміру, тому питаємо розмір спочатку.
                # _build_vision_messages() створює правильну відповідь.

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
        next_phase = "VISION_DONE"
        next_state = State.STATE_2_VISION.value
    else:
        # Unknown product - escalate to manager!
        next_phase = "ESCALATED"
        next_state = State.STATE_0_INIT.value

    # Determine escalation level
    escalation_level = "NONE"
    if not selected_products and not response.needs_clarification:
        # Product not identified and not asking for clarification = escalate
        escalation_level = "SOFT"  # Manager will see this in CRM

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
