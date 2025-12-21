"""
Vision Node - Response Builder.
===============================
Constructs the multi-bubble assistant response from Vision Agent results.
"""
from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from src.agents.pydantic.models import VisionResponse
from src.core.state_machine import State
from src.services.data.catalog_service import CatalogService

from ..utils import (
    extract_height_from_text,
    get_size_and_price_for_height,
    image_msg,
    text_msg,
)
from .snippets import get_product_snippet, get_snippet_by_header

logger = logging.getLogger(__name__)


def extract_products(
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

    if response.identified_product or response.needs_clarification:
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


def build_vision_messages(
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
        snippet_bubbles = get_product_snippet(product_name)
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
        unknown_snippet = get_snippet_by_header("Невідомий товар (ескалація)")
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
        error_snippet = get_snippet_by_header("Помилка розпізнавання фото")
        if error_snippet:
            for bubble in error_snippet:
                messages.append(text_msg(bubble))
        else:
            messages.append(text_msg("Не впізнала модель на фото 🤍"))
            messages.append(text_msg("Передаю менеджеру, щоб допоміг вам особисто!"))

    return messages


def build_vision_error_escalation(error_msg: str, step_number: int = 0) -> dict[str, Any]:
    """Build state update for vision error escalation."""
    escalation_messages = [
        text_msg("Не вдалося обробити фото. Передаю менеджеру."),
        text_msg("Будь ласка, очікуйте відповідь від менеджера."),
    ]

    return {
        "current_state": State.STATE_0_INIT.value,
        "messages": escalation_messages,
        "selected_products": [],
        "dialog_phase": "ESCALATED",
        "has_image": False,
        "image_url": None,
        "escalation_level": "HARD",
        "metadata": {
            "vision_error": error_msg[:200],
            "needs_clarification": False,
            "has_image": False,
            "escalation_level": "HARD",
            "escalation_reason": "vision_error",
        },
        "agent_response": {
            "messages": escalation_messages,
            "metadata": {
                "current_state": State.STATE_0_INIT.value,
                "intent": "PHOTO_IDENT",
                "escalation_level": "HARD",
            },
        },
        "step_number": step_number + 1,
    }
