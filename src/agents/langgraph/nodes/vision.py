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

import logging
import time
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


# =============================================================================
# HELPER FUNCTIONS (extracted for clarity)
# =============================================================================


async def _enrich_product_from_db(product_name: str, color: str | None = None) -> dict[str, Any] | None:
    """Lookup product in DB by name (and color if provided) and return enriched data.

    Використовується, коли Vision повернув назву без ціни/фото.
    ВАЖЛИВО: Якщо є колір - шукає з кольором для точного match!
    """
    try:
        catalog = CatalogService()
        
        # Якщо колір вже в назві (наприклад "Костюм Ритм (рожевий)") - не дублюємо
        search_query = product_name
        if color and f"({color})" not in product_name.lower() and color.lower() not in product_name.lower():
            # Спробуємо знайти точний match з кольором
            search_query = f"{product_name} ({color})"
        
        results = await catalog.search_products(query=search_query, limit=5)
        
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
            logger.info(
                "📦 Enriched from DB: %s (color=%s) -> %s, photo=%s",
                product_name, color, price_display, 
                photo_url[:50] if photo_url else "<no photo>"
            )
            return {
                "id": product.get("id", 0),
                "name": product.get("name", product_name),
                "price": CatalogService.get_price_for_size(product),
                "price_display": price_display,
                "color": (product.get("colors") or [""])[0]
                if isinstance(product.get("colors"), list)
                else product.get("colors", ""),
                "photo_url": photo_url,
                "description": product.get("description", ""),
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
        logger.info("Vision identified: %s (confidence=%.0f%%)", 
                   response.identified_product.name, confidence * 100)

    # Only show alternatives if NOT confident enough
    # High confidence = we know what it is, no need to confuse user with options
    if response.alternative_products and confidence < 0.85:
        products.extend([p.model_dump() for p in response.alternative_products])
        logger.info("Vision alternatives: %d (showing because confidence < 85%%)", 
                   len(response.alternative_products))
    elif response.alternative_products:
        logger.info("Vision: skipping %d alternatives (confidence=%.0f%% >= 85%%)",
                   len(response.alternative_products), confidence * 100)

    return products


def _build_vision_messages(
    response: VisionResponse,
    previous_messages: list[Any],
    vision_greeted: bool,
    user_message: str = "",
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

    # 1. Greeting: один раз на першу фото-взаємодію в сесії
    if not vision_greeted:
        messages.append(text_msg("Вітаю 🎀 З вами MIRT_UA, менеджер Ольга."))

    # 2. Product highlight БЕЗ ЦІНИ (ціна тільки після зросту!)
    # НЕ використовуємо reply_to_user від LLM - будуємо відповідь самі з точними даними з БД
    product = response.identified_product
    if product:
        # БАБЛА 2: Назва товару + колір (БЕЗ ЦІНИ!)
        # Ціна буде показана тільки після того як клієнт вкаже зріст
        product_name = product.name
        
        # Check if color is already in the name (e.g., "Костюм Ритм (рожевий)")
        # to avoid duplication like "Костюм Ритм (рожевий) у кольорі рожевий"
        color_already_in_name = (
            product.color and 
            product.color.lower() in product_name.lower()
        )
        
        if color_already_in_name:
            # Color is in name - just use the name
            message_text = f"Це наш {product_name} 💛"
        elif product.color:
            # Color NOT in name - add it
            message_text = f"Це наш {product_name} у кольорі {product.color} 💛"
        else:
            # No color info at all
            message_text = f"Це наш {product_name} 💛"
        
        messages.append(text_msg(message_text))
        
        # БАБЛА 3: Якщо зріст вже в тексті (фото + текст разом) - показуємо ціну одразу!
        # Інакше питаємо зріст, і agent_node обробить відповідь
        height = extract_height_from_text(user_message)
        if height:
            # Зріст є в тексті разом з фото - показуємо ціну одразу!
            size_label, price = get_size_and_price_for_height(height)
            messages.append(text_msg(f"На {height} см підійде розмір {size_label}"))
            messages.append(text_msg(f"Ціна {price} грн"))
            messages.append(text_msg("Оформлюємо? 🌸"))
        else:
            # Тільки фото без зросту - питаємо
            messages.append(text_msg("На який зріст підказати? 🌸"))

        # БАБЛА 4: Фото товару (якщо є)
        if product.photo_url:
            messages.append(image_msg(product.photo_url))

    # 4. Clarification (тільки якщо НЕ впізнали товар)
    elif response.clarification_question:
        messages.append(text_msg(response.clarification_question.strip()))
    elif response.needs_clarification:
        messages.append(text_msg("Не можу точно визначити модель. Підкажіть, будь ласка, що це за товар? 🤍"))

    # 5. Fallback
    if not messages:
        messages.append(
            text_msg(
                "Не впізнала модель на фото. Можу показати популярні варіанти - скажіть, який тип або колір цікавить, і на який зріст шукаєте."
            )
        )

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
    messages = state.get("messages", [])

    # Extract user message
    from .utils import extract_user_message

    user_message = extract_user_message(messages) or "Аналіз фото"

    # Build deps with image context
    deps = create_deps_from_state(state)
    deps.has_image = True
    deps.image_url = state.get("image_url") or state.get("metadata", {}).get("image_url")
    deps.current_state = State.STATE_2_VISION.value

    logger.info(
        "🖼️ [SESSION %s] Vision node started: image=%s",
        session_id,
        deps.image_url[:60] if deps.image_url else "None",
    )

    try:
        # Call vision agent
        response = await run_vision(message=user_message, deps=deps)

        # Enrich product from DB if Vision returned partial data (missing id/photo/price)
        if response.identified_product and (
            response.identified_product.price == 0
            or not response.identified_product.photo_url
            or not response.identified_product.id
        ):
            # Передаємо колір для точного match в БД!
            vision_color = response.identified_product.color
            enriched = await _enrich_product_from_db(
                response.identified_product.name, 
                color=vision_color
            )
            if enriched:
                # Update identified_product with DB data (DB = єдине джерело правди)
                response.identified_product.price = enriched.get("price", 0)
                response.identified_product.photo_url = enriched.get("photo_url", "")
                # Зберігаємо колір від vision якщо він є, інакше беремо з БД
                if not vision_color:
                    response.identified_product.color = enriched.get("color", "")
                response.identified_product.id = enriched.get("id", 0)

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
        )

        # Metrics
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_agent_step(
            session_id=session_id,
            state=State.STATE_2_VISION.value,
            intent="PHOTO_IDENT",
            event="vision_complete",
            latency_ms=latency_ms,
            extra={
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
        # Перевіряємо чи зріст вже є в тексті
        height_in_text = extract_height_from_text(user_message)
        
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
            next_phase = "INIT"
            next_state = State.STATE_0_INIT.value

        return {
            "current_state": next_state,
            "messages": assistant_messages,
            "selected_products": selected_products,
            "dialog_phase": next_phase,
            # ВАЖЛИВО: Скидаємо has_image після обробки!
            # Це запобігає повторному входу в vision при наступних текстових повідомленнях
            "has_image": False,
            "metadata": {
                **state.get("metadata", {}),
                "vision_confidence": response.confidence,
                "needs_clarification": response.needs_clarification,
                "has_image": False,  # Також в metadata
                "vision_greeted": True,  # greeting уже відправлено
            },
            # Lightweight agent_response so renderers (Telegram/ManyChat) можуть показати фото/текст
            "agent_response": {
                "event": "simple_answer",
                "messages": [
                    {"type": "text", "content": m.get("content", "")}
                    for m in assistant_messages
                    if m.get("type") == "text"
                ],
                "products": selected_products,
                "metadata": {
                    "session_id": session_id,
                    "current_state": next_state,
                    "intent": "PHOTO_IDENT",
                    "escalation_level": "NONE",
                },
            },
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
        }

    except Exception as e:
        logger.exception("Vision node failed: %s", e)
        return {
            "last_error": str(e),
            "tool_errors": [*state.get("tool_errors", []), f"Vision error: {e}"],
            "retry_count": state.get("retry_count", 0) + 1,
            "step_number": state.get("step_number", 0) + 1,
        }
