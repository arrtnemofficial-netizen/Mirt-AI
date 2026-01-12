"""
Output Parser Service.
======================
Handles parsing of LLM outputs (JSON) and conversion between
internal agent response models and core application models.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.models import (
    AgentResponse,
    Escalation,
    Message,
    Metadata,
    Product,
)

logger = logging.getLogger(__name__)


class TransitionResult:
    """Stub for validate_state_transition result."""

    def __init__(self, new_state: str, was_corrected: bool = False, reason: str | None = None):
        self.new_state = new_state
        self.was_corrected = was_corrected
        self.reason = reason


def parse_llm_output(
    content: str,
    session_id: str = "",
    current_state: str = "STATE_0_INIT",
) -> AgentResponse:
    """
    Parse LLM output to AgentResponse.

    Handles structured JSON format from LangGraph nodes containing:
    - event, messages, products, metadata fields
    """
    # Try to extract from result_state if it's already structured
    if not content:
        return AgentResponse(
            event="reply",
            messages=[Message(type="text", content="")],
            metadata=Metadata(session_id=session_id, current_state=current_state),
        )

    try:
        # Parse JSON content from LangGraph nodes
        parsed = json.loads(content)

        # Extract messages array (support both text and image types)
        messages_data = parsed.get("messages", [])
        messages = []
        for msg in messages_data:
            msg_type = msg.get("type", "text")
            content_value = msg.get("content") or msg.get("text") or msg.get("url", "")

            if msg_type == "image" and content_value:
                # Image message: content should be URL
                messages.append(Message(type="image", content=content_value))
            elif msg_type == "text" and content_value:
                # Text message
                messages.append(Message(type="text", content=content_value))

        # Extract products array
        products_data = parsed.get("products", [])
        products = []
        for prod in products_data:
            # Convert dict to Product object
            if isinstance(prod, dict):
                products.append(Product(**prod))

        # Extract metadata
        metadata_data = parsed.get("metadata", {})
        metadata = Metadata(
            session_id=metadata_data.get("session_id", session_id),
            current_state=metadata_data.get("current_state", current_state),
            intent=metadata_data.get("intent", ""),
            escalation_level=metadata_data.get("escalation_level", "NONE"),
        )

        return AgentResponse(
            event=parsed.get("event", "simple_answer"),
            messages=messages,
            products=products,
            metadata=metadata,
        )

    except (json.JSONDecodeError, Exception):
        # Fallback: treat as plain text content
        return AgentResponse(
            event="reply",
            messages=[Message(type="text", content=content)],
            metadata=Metadata(session_id=session_id, current_state=current_state),
        )


def convert_support_response(
    data: dict[str, Any], session_id: str
) -> AgentResponse:
    """
    Convert SupportResponse (PydanticAI) to AgentResponse (core/models).

    Handles schema differences between the two models:
    - EscalationInfo (no level) -> Escalation (has level)
    - ResponseMetadata -> Metadata (extra fields)
    - ProductMatch -> Product (compatible)
    """
    # Extract messages
    raw_messages = data.get("messages", [])
    messages = [
        Message(
            type=m.get("type", "text"),
            content=m.get("content") or m.get("text") or "",
        )
        for m in raw_messages
    ]
    if not messages:
        messages = [Message(type="text", content="")]

    # Extract metadata
    raw_meta = data.get("metadata", {})
    metadata = Metadata(
        session_id=raw_meta.get("session_id", session_id),
        current_state=raw_meta.get("current_state", "STATE_0_INIT"),
        intent=raw_meta.get("intent", "UNKNOWN_OR_EMPTY"),
        escalation_level=raw_meta.get("escalation_level", "NONE"),
    )

    # Extract escalation (add level from metadata if missing)
    escalation = None
    raw_esc = data.get("escalation")
    if raw_esc:
        escalation = Escalation(
            level=raw_esc.get("level", raw_meta.get("escalation_level", "L1")),
            reason=raw_esc.get("reason", "Escalation requested"),
            target=raw_esc.get("target", "human_operator"),
        )

    # Extract products (ProductMatch -> Product compatible)
    products = []
    for idx, p in enumerate(data.get("products", [])):
        try:
            # Some upstream agents return id=0/photo_url=""; make it display-safe
            product_id = p.get("id") or p.get("product_id") or (idx + 1)
            price = p.get("price") or 0
            photo_url = p.get("photo_url") or p.get("image_url") or ""

            # Fallbacks to satisfy schema (id > 0, price > 0)
            if not product_id or int(product_id) <= 0:
                product_id = idx + 1
            if price == 0:
                # Minimal positive price to pass validation; actual amount is in text
                price = 1

            products.append(
                Product(
                    id=int(product_id),
                    name=p.get("name", ""),
                    size=p.get("size", "") or "",
                    color=p.get("color", "") or "",
                    price=float(price),
                    photo_url=photo_url,
                )
            )
        except Exception as exc:
            logger.debug("Skipping product in response conversion: %s", exc)

    return AgentResponse(
        event=data.get("event", "simple_answer"),
        messages=messages,
        products=products,
        metadata=metadata,
        escalation=escalation,
    )
