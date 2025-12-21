"""
Vision Node - Response Builder.
===============================
Constructs the multi-bubble assistant response from Vision Agent results.
"""
from __future__ import annotations

import json
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


def _get_builder_templates() -> dict[str, Any]:
    """Load vision builder templates from registry."""
    bubbles = get_snippet_by_header("VISION_BUILDER_TEMPLATES")
    if not bubbles:
        return {}
    try:
        data = json.loads(bubbles[0])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


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
    1. Greeting (if first message): no mention of AI/bot
    2. Product: name + color
    3. Price or height request
    4. Photo: [product image]

    If product NOT found:
    - Clarification question from LLM or fallback
    """
    messages: list[dict[str, str]] = []
    confidence = response.confidence or 0.0
    templates = _get_builder_templates()

    def _tpl(key: str, default: str) -> str:
        value = templates.get(key)
        return value if isinstance(value, str) and value else default

    def _tpl_list(key: str) -> list[str]:
        value = templates.get(key, [])
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return []

    def _history_has_greeting(prev: list[Any]) -> bool:
        try:
            keywords = [kw.lower() for kw in _tpl_list("greeting_keywords")]
            for m in prev or []:
                if isinstance(m, dict):
                    content = str(m.get("content") or "")
                    if any(kw in content.lower() for kw in keywords):
                        return True
        except Exception:
            return False
        return False

    def _norm_color(s: str) -> str:
        return " ".join((s or "").lower().strip().split())

    def _is_ambiguous_color(s: str) -> bool:
        ss = _norm_color(s)
        separators = _tpl_list("ambiguous_color_separators") or ["/"]
        return any(sep in ss for sep in separators)

    # 1. Greeting: once per session for the first photo interaction
    if (not vision_greeted) or (not _history_has_greeting(previous_messages)):
        greeting_bubbles = get_snippet_by_header("VISION_GREETING")
        greeting_text = greeting_bubbles[0] if greeting_bubbles else "Hello"
        messages.append(text_msg(greeting_text))

    # 2. Product highlight without price (price comes after height)
    # Build the response from catalog data (not LLM free-text)
    product = response.identified_product
    if product:
        # Bubble: product name + color (no price here)
        product_name = product.name

        # Avoid duplication like "Product (red) in color red"
        color_already_in_name = product.color and product.color.lower() in product_name.lower()

        prefix = _tpl("product_prefix_strong", "This is our")
        if confidence < 0.5:
            prefix = _tpl("product_prefix_uncertain", "Looks like our")

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

        line_plain = _tpl("product_line_plain", "{prefix} {product_name}")
        line_color = _tpl("product_line_color", "{prefix} {product_name} in {color}")

        if color_already_in_name:
            message_text = line_plain.format(prefix=prefix, product_name=product_name)
        elif product.color and (not needs_color_confirmation):
            message_text = line_color.format(
                prefix=prefix,
                product_name=product_name,
                color=product.color,
            )
        else:
            message_text = line_plain.format(prefix=prefix, product_name=product_name)

        messages.append(text_msg(message_text))

        # Try to get a product snippet from snippets.md
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
            prompt = _tpl(
                "color_prompt",
                "Please confirm the color: {options}.",
            ).format(options=options_text)
            messages.append(text_msg(prompt))

        # If height is present in the text, show price immediately; otherwise ask for height.
        height = extract_height_from_text(user_message)
        if height:
            size_label, price = get_size_and_price_for_height(height)
            if catalog_product:
                with suppress(Exception):
                    price = int(CatalogService.get_price_for_size(catalog_product, size_label))
            size_line = _tpl(
                "size_line",
                "Height {height} cm fits size {size_label}.",
            ).format(height=height, size_label=size_label)
            price_line = _tpl(
                "price_line",
                "Price {price}.",
            ).format(price=price)
            confirm_line = _tpl(
                "confirm_line",
                "Shall we proceed?",
            )
            messages.append(text_msg(size_line))
            messages.append(text_msg(price_line))
            messages.append(text_msg(confirm_line))
        else:
            ask_height = _tpl(
                "ask_height",
                "What height should we use?",
            )
            messages.append(text_msg(ask_height))

    # 4. Clarification (only if product not identified)
    elif response.clarification_question:
        messages.append(text_msg(response.clarification_question.strip()))
    elif response.needs_clarification:
        clarification = _tpl(
            "clarification_fallback",
            "Please clarify the product details.",
        )
        messages.append(text_msg(clarification))

    # If still no product and no clarification, treat as not our product.
    if (
        (not response.identified_product)
        and (not response.clarification_question)
        and (not response.needs_clarification)
    ):
        # Try to get snippet for unknown product
        unknown_snippet = get_snippet_by_header("VISION_UNKNOWN_PRODUCT_ESCALATION")
        if unknown_snippet:
            for bubble in unknown_snippet[:3]:  # Max 3 bubbles
                messages.append(text_msg(bubble))
        else:
            messages.append(text_msg(_tpl("unknown_fallback_line1", "We do not carry this model.")))
            messages.append(text_msg(_tpl("unknown_fallback_line2", "We can suggest alternatives.")))
            messages.append(text_msg(_tpl("unknown_fallback_line3", "Want similar options?")))

    # 5. Fallback - use photo recognition error snippet
    if not messages:
        error_snippet = get_snippet_by_header("VISION_PHOTO_RECO_ERROR")
        if error_snippet:
            for bubble in error_snippet:
                messages.append(text_msg(bubble))
        else:
            messages.append(text_msg(_tpl("error_no_match_line1", "Could not identify the model.")))
            messages.append(text_msg(_tpl("error_no_match_line2", "Forwarding to a manager.")))

    return messages


def build_vision_error_escalation(error_msg: str, step_number: int = 0) -> dict[str, Any]:
    """Build state update for vision error escalation."""
    templates = _get_builder_templates()

    def _tpl(key: str, default: str) -> str:
        value = templates.get(key)
        return value if isinstance(value, str) and value else default

    escalation_messages = [
        text_msg(_tpl("escalation_line1", "Photo processing failed. Escalating.")),
        text_msg(_tpl("escalation_line2", "Please wait for a manager response.")),
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
