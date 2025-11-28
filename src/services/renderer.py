"""Helpers to render AgentResponse objects for chat platforms."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from src.core.models import AgentResponse, Message, Product


def format_product(product: Product) -> str:
    """Human-friendly single-line product description."""

    parts = [
        f"{product.name} ({product.size}, {product.color})",
        f"₴{product.price:,.2f}".replace(",", " "),
    ]
    if product.sku:
        parts.append(f"SKU {product.sku}")
    if product.photo_url:
        parts.append(product.photo_url)
    return " — ".join(parts)


def render_messages_text(messages: list[Message]) -> list[str]:
    """Flatten text messages for text-only channels (e.g., Telegram)."""

    output: list[str] = []
    for message in messages:
        if message.type == "text":
            output.append(message.content)
    return output


def render_agent_response_text(response: AgentResponse) -> list[str]:
    """Prepare a list of textual chunks including product suggestions."""

    chunks = render_messages_text(response.messages)
    if response.products:
        product_lines = ["Пропозиції:"] + [f"• {format_product(p)}" for p in response.products]
        chunks.append("\n".join(product_lines))
    return chunks
