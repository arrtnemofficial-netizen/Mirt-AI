"""
Fallbacks - graceful degradation responses.
============================================
Fallback responses when external services are unavailable.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header


logger = logging.getLogger(__name__)


class FallbackType(Enum):
    """Fallback scenario types."""

    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_TIMEOUT = "llm_timeout"
    SUPABASE_UNAVAILABLE = "supabase_unavailable"
    MANYCHAT_UNAVAILABLE = "manychat_unavailable"
    VISION_FAILED = "vision_failed"
    CATALOG_EMPTY = "catalog_empty"
    PAYMENT_ERROR = "payment_error"
    CRM_UNAVAILABLE = "crm_unavailable"
    RATE_LIMITED = "rate_limited"
    UNKNOWN_ERROR = "unknown_error"


def _get_snippet_text(header: str, default: str) -> str:
    """Helper to get snippet text from registry."""
    s = get_snippet_by_header(header)
    return "\n".join(s) if s else default


def get_fallback_messages_map() -> dict[FallbackType, dict[str, Any]]:
    """Get mapping of fallback types to messages from registry."""
    return {
        FallbackType.LLM_UNAVAILABLE: {
            "text": _get_snippet_text("FALLBACK_LLM_UNAVAILABLE", "Technical difficulties. Please try again or contact support."),
            "quick_replies": [], # Simplified for now, could be externalized too if needed
            "should_escalate": False,
            "retry_after_seconds": 60,
        },
        FallbackType.LLM_TIMEOUT: {
            "text": _get_snippet_text("FALLBACK_LLM_TIMEOUT", "Thinking too long... Please repeat your question."),
            "quick_replies": [],
            "should_escalate": False,
            "retry_after_seconds": 30,
        },
        FallbackType.SUPABASE_UNAVAILABLE: {
            "text": _get_snippet_text("FALLBACK_SUPABASE_UNAVAILABLE", "Cannot save data right now, but please continue!"),
            "quick_replies": [],
            "should_escalate": False,
            "retry_after_seconds": 120,
        },
        FallbackType.MANYCHAT_UNAVAILABLE: {
            "text": None,
            "quick_replies": [],
            "should_escalate": True,
            "retry_after_seconds": 60,
        },
        FallbackType.VISION_FAILED: {
            "text": _get_snippet_text("FALLBACK_VISION_FAILED", "Could not recognize photo. Please describe or try another."),
            "quick_replies": [],
            "should_escalate": False,
            "retry_after_seconds": 0,
        },
        FallbackType.CATALOG_EMPTY: {
            "text": _get_snippet_text("FALLBACK_CATALOG_EMPTY", "Item not found in catalog. Please describe further."),
            "quick_replies": [],
            "should_escalate": False,
            "retry_after_seconds": 0,
        },
        FallbackType.PAYMENT_ERROR: {
            "text": _get_snippet_text("FALLBACK_PAYMENT_ERROR", "Order failed. Manager will contact you soon!"),
            "quick_replies": [],
            "should_escalate": True,
            "retry_after_seconds": 0,
        },
        FallbackType.CRM_UNAVAILABLE: {
            "text": _get_snippet_text("FALLBACK_CRM_UNAVAILABLE", "Order received! Manager will contact you for confirmation."),
            "quick_replies": [],
            "should_escalate": True,
            "retry_after_seconds": 300,
        },
        FallbackType.RATE_LIMITED: {
            "text": _get_snippet_text("FALLBACK_RATE_LIMITED", "Too many messages. Please wait and try again."),
            "quick_replies": [],
            "should_escalate": False,
            "retry_after_seconds": 30,
        },
        FallbackType.UNKNOWN_ERROR: {
            "text": _get_snippet_text("FALLBACK_UNKNOWN_ERROR", "Something went wrong. Please try again or use /restart."),
            "quick_replies": [],
            "should_escalate": False,
            "retry_after_seconds": 10,
        },
    }


def get_fallback_response(
    fallback_type: FallbackType,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get fallback response for error type."""
    messages_map = get_fallback_messages_map()
    fallback = messages_map.get(fallback_type, messages_map[FallbackType.UNKNOWN_ERROR])

    logger.warning(
        "Fallback triggered: type=%s, escalate=%s, context=%s",
        fallback_type.value,
        fallback.get("should_escalate"),
        context,
    )

    return {
        "text": fallback["text"],
        "quick_replies": fallback.get("quick_replies", []),
        "should_escalate": fallback.get("should_escalate", False),
        "retry_after_seconds": fallback.get("retry_after_seconds", 0),
        "fallback_type": fallback_type.value,
    }


def get_fallback_text(fallback_type: FallbackType) -> str | None:
    """Get fallback text only."""
    messages_map = get_fallback_messages_map()
    fallback = messages_map.get(fallback_type, messages_map[FallbackType.UNKNOWN_ERROR])
    return fallback.get("text")


def should_escalate(fallback_type: FallbackType) -> bool:
    """Check if escalation is needed."""
    messages_map = get_fallback_messages_map()
    fallback = messages_map.get(fallback_type, {})
    return fallback.get("should_escalate", False)


def get_contextual_fallback(
    error: Exception,
    current_state: str | None = None,
    intent: str | None = None,
) -> dict[str, Any]:
    """Determine fallback type based on error and context."""
    error_str = str(error).lower()
    error_type = type(error).__name__

    if "timeout" in error_str or "timed out" in error_str:
        fallback_type = FallbackType.LLM_TIMEOUT
    elif "rate limit" in error_str or "429" in error_str:
        fallback_type = FallbackType.RATE_LIMITED
    elif "supabase" in error_str or "postgres" in error_str:
        fallback_type = FallbackType.SUPABASE_UNAVAILABLE
    elif "manychat" in error_str:
        fallback_type = FallbackType.MANYCHAT_UNAVAILABLE
    elif "vision" in error_str or "image" in error_str:
        fallback_type = FallbackType.VISION_FAILED
    elif "crm" in error_str or "snitkix" in error_str:
        fallback_type = FallbackType.CRM_UNAVAILABLE
    elif "payment" in (current_state.lower() if current_state else ""):
        fallback_type = FallbackType.PAYMENT_ERROR
    else:
        fallback_type = FallbackType.UNKNOWN_ERROR

    return get_fallback_response(
        fallback_type,
        context={
            "error_type": error_type,
            "current_state": current_state,
            "intent": intent,
        },
    )


def get_cached_response(intent: str) -> str | None:
    """Get cached response for basic intents from registry."""
    intent_lower = intent.lower() if intent else ""

    if "greet" in intent_lower or "hello" in intent_lower:
        return _get_snippet_text("CACHED_GREETING", "Hi! I'm Mirt - your personal shopping assistant.")
    if "catalog" in intent_lower or "product" in intent_lower:
        return _get_snippet_text("CACHED_CATALOG", "We offer children's costumes. Send a photo or description!")
    if "payment" in intent_lower or "order" in intent_lower:
        return _get_snippet_text("CACHED_PAYMENT", "To order: name, phone, city, and Nova Poshta branch.")
    if "help" in intent_lower:
        return _get_snippet_text("CACHED_HELP", "I can help you pick a costume by photo or description. Tell me the child's height!")

    return None
