"""
Response Builder - Build multi-bubble vision responses.

This module handles building multi-bubble assistant responses from VisionResponse.
Extracted from vision.py for better testability and maintainability.
"""

from contextlib import suppress
from typing import TYPE_CHECKING, Any

from src.services.catalog import CatalogService

from ...utils import (
    extract_height_from_text,
    get_size_and_price_for_height,
    get_size_recommendation_text,
    image_msg,
    text_msg,
)

if TYPE_CHECKING:
    from src.agents.pydantic.models import VisionResponse

from .snippet_loader import get_product_snippet, get_snippet_by_header


def build_vision_messages(
    response: "VisionResponse",
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

    Args:
        response: VisionResponse from vision agent
        previous_messages: Previous conversation messages
        vision_greeted: Whether vision has already greeted in this session
        user_message: User's message text
        catalog_product: Enriched product from catalog (optional)

    Returns:
        List of message dicts (text_msg/image_msg format)
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
    # CRITICAL: Use AND (not OR) to prevent repeat greeting when history is trimmed/missing
    if (not vision_greeted) and (not _history_has_greeting(previous_messages)):
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

        # Try to get beautiful presentation text using presentation builder
        # Priority: snippets.md → YAML (visual) → Supabase description (formatted nicely)
        from .presentation_builder import build_presentation_text
        
        # Try to load YAML product data if available
        yaml_product = None
        try:
            from .product_colors import _load_products_master
            master = _load_products_master()
            products_yaml = master.get("products", {})
            product_name_norm = " ".join(product_name.strip().split()).lower()
            for product_key, product_data in products_yaml.items():
                if isinstance(product_data, dict):
                    product_name_in_yaml = product_data.get("name", "").strip().lower()
                    if product_name_norm == product_name_in_yaml:
                        yaml_product = product_data
                        break
        except Exception:
            pass  # YAML loading failed, continue without it
        
        presentation_text = build_presentation_text(
            product_name=product_name,
            product_color=product.color,
            catalog_product=catalog_product,
            yaml_product=yaml_product,
        )
        
        # Show description bubble ONLY if snippet exists
        # If no snippet, skip description bubble entirely
        if presentation_text:
            messages.append(text_msg(presentation_text))

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
            # Використовуємо новий формат рекомендації з максимальним зростом
            recommendation_text = get_size_recommendation_text(size_label)
            messages.append(text_msg(recommendation_text))
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

