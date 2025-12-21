"""
Human-like Response Generator.
==============================
Makes AI responses feel like a real human.
"""

from __future__ import annotations

import random
from typing import Literal, TYPE_CHECKING


if TYPE_CHECKING:
    from typing import list


# =============================================================================
# PUBLIC API
# =============================================================================

ResponseType = Literal[
    "timeout",
    "error",
    "photo_error",
    "photo_analysis_error",
    "payment_error",
    "escalation",
    "not_found",
]


def get_human_response(response_type: ResponseType) -> str:
    """
    Get a random human-like response for the given situation from PromptRegistry.
    """
    from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header

    header_map: dict[ResponseType, str] = {
        "timeout": "HUMAN_TIMEOUT_RESPONSES",
        "error": "HUMAN_ERROR_RESPONSES",
        "photo_error": "HUMAN_PHOTO_ERROR_RESPONSES",
        "photo_analysis_error": "HUMAN_PHOTO_ANALYSIS_ERROR_RESPONSES",
        "payment_error": "HUMAN_PAYMENT_ERROR_RESPONSES",
        "escalation": "HUMAN_ESCALATION_RESPONSES",
        "not_found": "HUMAN_NOT_FOUND_RESPONSES",
    }

    header = header_map.get(response_type, "HUMAN_ERROR_RESPONSES")
    variants = get_snippet_by_header(header)
    if not variants:
        import json
        # Extreme fallback if registry fails
        labels_json = get_snippet_by_header("VISION_LABELS")
        labels = json.loads(labels_json[0]) if labels_json else {}
        return labels.get("fallback_typing", "One moment, checking.")
        
    return random.choice(variants)


def get_typing_indicator() -> str:
    """Get a random typing indicator from registry."""
    from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header
    
    variants = get_snippet_by_header("HUMAN_TYPING_PHRASES")
    if not variants:
        return "..."
        
    return random.choice(variants)


def add_human_touch(text: str, typo_chance: float = 0.05) -> str:
    """
    Optionally add small human touches to text.
    """
    if typo_chance <= 0:
        return text

    if random.random() < typo_chance and text and text[-1] == ".":
        return text[:-1]

    return text


# =============================================================================
# TYPING DELAY CONFIGURATION
# =============================================================================

TYPING_DELAY_MIN = 0.8
TYPING_DELAY_MAX = 2.5
TYPING_DELAY_PER_CHAR = 0.02


def calculate_typing_delay(response_length: int) -> float:
    """Calculate realistic typing delay based on response length."""
    base_delay = random.uniform(TYPING_DELAY_MIN, TYPING_DELAY_MAX)
    char_delay = min(response_length * TYPING_DELAY_PER_CHAR, 3.0)
    return base_delay + char_delay
