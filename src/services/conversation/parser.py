"""LLM output parsing functions.

These functions handle parsing of LangGraph node outputs
into structured AgentResponse objects.
"""

from __future__ import annotations

import json

from src.core.models import AgentResponse, Message, Metadata, Product
from src.services.conversation.models import TransitionResult


def parse_llm_output(
    content: str,
    session_id: str = "",
    current_state: str = "STATE_0_INIT",
) -> AgentResponse:
    """Parse LLM output to AgentResponse.

    Handles structured JSON format from LangGraph nodes containing:
    - event, messages, products, metadata fields
    """
    if not content:
        return AgentResponse(
            event="reply",
            messages=[Message(type="text", content="")],
            metadata=Metadata(session_id=session_id, current_state=current_state),
        )

    try:
        parsed = json.loads(content)

        # Extract messages array
        messages_data = parsed.get("messages", [])
        messages = []
        for msg in messages_data:
            content_value = msg.get("content") or msg.get("text")
            if msg.get("type") == "text" and content_value:
                messages.append(Message(type="text", content=content_value))

        # Extract products array
        products_data = parsed.get("products", [])
        products = []
        for prod in products_data:
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


def validate_state_transition(
    session_id: str,
    current_state: str,
    proposed_state: str,
    intent: str = "",
) -> TransitionResult:
    """STUB: Validate state transition.

    In NEW architecture: LangGraph edges make invalid transitions impossible.
    This stub just accepts all transitions for legacy compatibility.
    """
    return TransitionResult(new_state=proposed_state, was_corrected=False)
