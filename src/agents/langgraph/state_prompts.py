"""
State-Specific Prompts for Turn-Based State Machine.
=====================================================
Each state has its own prompt with:
- Clear instructions
- Output format (OUTPUT)
- Transition conditions
- Bans

Matches the n8n state machine 1:1.
"""

from __future__ import annotations

from typing import Any


# =============================================================================
# STATE PROMPTS (Ukrainian, matching n8n exactly)
# =============================================================================

STATE_PROMPTS: dict[str, str] = {}


# =============================================================================
# PAYMENT SUB-PHASES
# =============================================================================

PAYMENT_SUB_PHASES = {
    "REQUEST_DATA": "STATE_5_PAYMENT_DELIVERY_REQUEST",
    "CONFIRM_DATA": "STATE_5_PAYMENT_DELIVERY_CONFIRM",
    "SHOW_PAYMENT": "STATE_5_PAYMENT_DELIVERY_PAYMENT",
    "THANK_YOU": "STATE_5_PAYMENT_DELIVERY_THANKS",
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_state_prompt(state_name: str, sub_phase: str | None = None) -> str:
    """
    Get the prompt for a specific state.

    Single Source of Truth:
    - PromptRegistry (data/prompts/states/*.md)
    """
    # Support callers passing enum values (e.g. State.STATE_1_DISCOVERY)
    # Note: State is a StrEnum, so isinstance(state_name, str) returns True
    # We need to check for Enum first
    from enum import Enum

    from src.core.prompt_registry import registry

    if isinstance(state_name, Enum):
        state_name = state_name.value
    elif not isinstance(state_name, str):
        state_name = str(state_name)

    # Handle payment sub-phases specially
    if sub_phase and state_name == "STATE_5_PAYMENT_DELIVERY":
        key = PAYMENT_SUB_PHASES.get(sub_phase)
        if key:
            prompt_config = registry.get(f"state.{key}")
            return prompt_config.content

    prompt_config = registry.get(f"state.{state_name}")
    return prompt_config.content


def validate_payment_subphase_prompts() -> list[str]:
    from src.core.prompt_registry import registry

    missing: list[str] = []
    for key in PAYMENT_SUB_PHASES.values():
        try:
            registry.get(f"state.{key}")
        except (FileNotFoundError, ValueError):
            missing.append(key)
    return missing


from src.services.domain.payment.payment_validation import get_payment_sub_phase


def determine_next_dialog_phase(
    current_state: str,
    intent: str,
    has_products: bool,
    has_size: bool,
    has_color: bool,
    user_confirmed: bool,
    payment_sub_phase: str | None = None,
) -> str:
    """
    Determine the next dialog_phase based on current state and conditions.

    This is the CORE transition logic matching n8n state machine.
    """
    # STATE_0_INIT transitions
    if current_state == "STATE_0_INIT":
        if intent in {"GREETING_ONLY", "DISCOVERY_OR_QUESTION"}:
            return "DISCOVERY"
        elif intent == "PHOTO_IDENT":
            return "VISION_DONE"
        elif intent in ("SIZE_HELP", "COLOR_HELP"):
            return "WAITING_FOR_SIZE"
        elif intent == "PAYMENT_DELIVERY":
            return "WAITING_FOR_DELIVERY_DATA"
        elif intent == "COMPLAINT":
            return "COMPLAINT"
        elif intent == "THANKYOU_SMALLTALK":
            return "COMPLETED"
        elif intent == "OUT_OF_DOMAIN":
            return "OUT_OF_DOMAIN"
        else:
            return "DISCOVERY"

    # STATE_1_DISCOVERY transitions
    if current_state == "STATE_1_DISCOVERY":
        if has_products and has_size:
            return "SIZE_COLOR_DONE"
        elif has_products:
            return "WAITING_FOR_SIZE"
        # FIXED: Handle intent-based transitions to avoid dead loops
        elif intent == "PAYMENT_DELIVERY" and user_confirmed:
            return "WAITING_FOR_DELIVERY_DATA"
        elif intent == "COMPLAINT":
            return "COMPLAINT"
        elif intent == "THANKYOU_SMALLTALK":
            return "COMPLETED"
        else:
            return "DISCOVERY"  # Stay in discovery until we have products

    # STATE_2_VISION transitions
    if current_state == "STATE_2_VISION":
        if has_products:
            return "WAITING_FOR_SIZE"
        # FIXED: If vision didn't find product, go to DISCOVERY for clarification
        # instead of staying in VISION_DONE which causes dead loop
        else:
            return "DISCOVERY"  # Let agent ask clarifying questions

    # STATE_3_SIZE_COLOR transitions
    if current_state == "STATE_3_SIZE_COLOR":
        if has_products and has_size and has_color:
            return "SIZE_COLOR_DONE"
        elif has_size:
            return "WAITING_FOR_COLOR"
        else:
            return "WAITING_FOR_SIZE"

    # STATE_4_OFFER transitions
    if current_state == "STATE_4_OFFER":
        if user_confirmed or intent == "PAYMENT_DELIVERY":
            return "WAITING_FOR_DELIVERY_DATA"
        else:
            return "OFFER_MADE"

    # STATE_5_PAYMENT_DELIVERY transitions
    if current_state == "STATE_5_PAYMENT_DELIVERY":
        phase_map = {
            "THANK_YOU": "UPSELL_OFFERED",
            "SHOW_PAYMENT": "WAITING_FOR_PAYMENT_PROOF",
            "CONFIRM_DATA": "WAITING_FOR_PAYMENT_METHOD",
        }
        return phase_map.get(payment_sub_phase, "WAITING_FOR_DELIVERY_DATA")

    # STATE_6_UPSELL transitions
    if current_state == "STATE_6_UPSELL":
        return "COMPLETED"

    # STATE_7_END
    if current_state == "STATE_7_END":
        return "COMPLETED"

    # STATE_8_COMPLAINT
    if current_state == "STATE_8_COMPLAINT":
        return "COMPLETED"

    # STATE_9_OOD
    if current_state == "STATE_9_OOD":
        return "COMPLETED"

    # Default
    return "INIT"


# =============================================================================
# INTENT KEYWORDS (for simple detection)
# =============================================================================
# SINGLE SOURCE OF TRUTH: Use get_intent_patterns() from intent.py
# This prevents keyword duplication and keeps detection consistent
#
# NOTE: We use lazy loading to avoid circular imports:
# state_prompts.py <- edges.py <- intent.py <- nodes/agent.py <- state_prompts.py

# Cached reference to avoid repeated imports
_INTENT_PATTERNS_CACHE: dict | None = None


def _get_intent_patterns() -> dict:
    """Lazy load INTENT_PATTERNS to avoid circular imports."""
    global _INTENT_PATTERNS_CACHE
    if _INTENT_PATTERNS_CACHE is None:
        from src.agents.langgraph.nodes.intent import get_intent_patterns

        _INTENT_PATTERNS_CACHE = get_intent_patterns()
    return _INTENT_PATTERNS_CACHE


def detect_simple_intent(message: str) -> str | None:
    """
    Simple keyword-based intent detection.

    Uses INTENT_PATTERNS from intent.py as Single Source of Truth.
    """
    patterns = _get_intent_patterns()
    message_lower = message.lower()

    # Check priority intents from INTENT_PATTERNS
    # ORDER MATTERS! Higher priority first.
    priority_intents = [
        "PAYMENT_DELIVERY",
        "COMPLAINT",
        "SIZE_HELP",
        "COLOR_HELP",
        "REQUEST_PHOTO",  # Before THANKYOU to catch "request photo"
        "PRODUCT_CATEGORY",
        "THANKYOU_SMALLTALK",  # Last - catch "thanks", "ok" at end
    ]

    for intent in priority_intents:
        keywords = patterns.get(intent, [])
        for keyword in keywords:
            if keyword in message_lower:
                return intent

    return None


# Legacy alias for backward compatibility
INTENT_KEYWORDS = {}  # Deprecated - use _get_intent_patterns() instead
