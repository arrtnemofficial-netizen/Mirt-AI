"""
State-Specific Prompts for Turn-Based State Machine.
=====================================================
Кожен стейт має свій промпт з:
- Чіткими інструкціями що робити
- Форматом відповіді (OUTPUT)
- Умовами переходу (transitions)
- Заборонами (bans)

Відповідає n8n state machine 1:1.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


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

    PRIORITY ORDER (Single Source of Truth):
    1. PromptRegistry (data/prompts/states/*.md) - PREFERRED
    2. STATE_PROMPTS dict - FALLBACK

    This allows editing prompts via .md files without code changes.
    """
    # Support callers passing enum values (e.g. State.STATE_1_DISCOVERY)
    # Note: State is a StrEnum, so isinstance(state_name, str) returns True
    # We need to check for Enum first
    from enum import Enum

    from src.conf.config import settings
    from src.core.prompt_registry import registry

    if isinstance(state_name, Enum):
        state_name = state_name.value
    elif not isinstance(state_name, str):
        state_name = str(state_name)

    # Handle payment sub-phases specially
    if sub_phase and state_name == "STATE_5_PAYMENT_DELIVERY":
        key = PAYMENT_SUB_PHASES.get(sub_phase)
        if key:
            # Try registry first for payment sub-phase
            try:
                prompt_config = registry.get(f"state.{key}")
                return prompt_config.content
            except (FileNotFoundError, ValueError):
                try:
                    from src.services.observability import track_metric

                    track_metric(
                        "state_prompt_fallback_used",
                        1,
                        {"state": key, "reason": "payment_subphase_missing_md"},
                    )
                except Exception:
                    pass
                # In production, missing prompt is a critical error
                import os
                env = os.getenv("ENVIRONMENT", "development").lower()
                is_production = env in ("production", "prod", "staging")
                
                if is_production or settings.DISABLE_CODE_STATE_PROMPTS_FALLBACK:
                    raise FileNotFoundError(
                        f"Missing markdown prompt for state.{key}. "
                        f"This is required in {env} environment. "
                        f"Create data/prompts/states/{key}.md"
                    )
                
                # Development fallback with warning
                logger.warning(
                    "Using fallback prompt for payment sub-phase state.%s (dev mode only). "
                    "Create data/prompts/states/%s.md for production.",
                    key,
                    key,
                )
                return STATE_PROMPTS.get(key, "")

    # PRIORITY 1: Try PromptRegistry (data/prompts/states/*.md)
    try:
        prompt_config = registry.get(f"state.{state_name}")
        return prompt_config.content
    except (FileNotFoundError, ValueError):
        pass

    # PRIORITY 2: Fallback to hardcoded STATE_PROMPTS
    # In production/staging, this fallback is disabled for safety
    import os
    env = os.getenv("ENVIRONMENT", "development").lower()
    is_production = env in ("production", "prod", "staging")
    
    # In production, missing prompt is a critical error
    if is_production or settings.DISABLE_CODE_STATE_PROMPTS_FALLBACK:
        raise FileNotFoundError(
            f"Missing markdown prompt for state.{state_name}. "
            f"This is required in {env} environment. "
            f"Create data/prompts/states/{state_name}.md"
        )
    
    # Development fallback with warning
    try:
        from src.services.observability import track_metric

        track_metric(
            "state_prompt_fallback_used",
            1,
            {"state": state_name, "reason": "missing_md", "environment": env},
        )
    except Exception:
        pass
    
    logger.warning(
        "Using fallback prompt for state.%s (dev mode only). "
        "Create data/prompts/states/%s.md for production.",
        state_name,
        state_name,
    )
    return STATE_PROMPTS.get(state_name, "")


def validate_payment_subphase_prompts() -> list[str]:
    from src.core.prompt_registry import registry

    missing: list[str] = []
    for key in PAYMENT_SUB_PHASES.values():
        try:
            registry.get(f"state.{key}")
        except (FileNotFoundError, ValueError):
            missing.append(key)
    return missing


def get_payment_sub_phase(state: dict[str, Any]) -> str:
    """
    Determine which sub-phase of payment we're in.

    Based on what data we have AND user message content:
    - No customer data → REQUEST_DATA
    - Has customer data, not confirmed → CONFIRM_DATA
    - Confirmed, no payment → SHOW_PAYMENT
    - User says "оплатила/оплатив" → SHOW_PAYMENT (waiting for proof)
    - Has payment proof → THANK_YOU
    """
    metadata = state.get("metadata", {})
    
    # Check user message for payment confirmation keywords
    messages = state.get("messages", [])
    user_message = ""
    for msg in reversed(messages):
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
        elif hasattr(msg, "type") and getattr(msg, "type", "") == "human":
            user_message = getattr(msg, "content", "")
            break
    
    user_message_lower = user_message.lower() if user_message else ""
    payment_confirmation_keywords = [
        "оплатила", "оплатив", "переказала", "переказав",
        "відправила скрін", "відправив скрін", "скрін", "квитанцію",
        "доказ оплати", "оплачено", "переказано"
    ]
    user_says_paid = any(keyword in user_message_lower for keyword in payment_confirmation_keywords)

    # Check if we have customer data
    has_name = bool(metadata.get("customer_name"))
    has_phone = bool(metadata.get("customer_phone"))
    has_city = bool(metadata.get("customer_city"))
    has_np = bool(metadata.get("customer_nova_poshta"))

    has_customer_data = has_name and has_phone and has_city and has_np

    # Check if data is confirmed
    data_confirmed = metadata.get("delivery_data_confirmed", False)

    # Check if payment proof received
    payment_proof = metadata.get("payment_proof_received", False)

    if payment_proof:
        return "THANK_YOU"
    elif user_says_paid:
        # User says they paid → we're waiting for proof (screenshot)
        return "SHOW_PAYMENT"
    elif data_confirmed:
        return "SHOW_PAYMENT"
    elif has_customer_data:
        return "CONFIRM_DATA"
    else:
        return "REQUEST_DATA"


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
        # CRITICAL: Map sub-phase to dialog_phase deterministically
        # SHOW_PAYMENT means we showed payment details and are waiting for proof (screenshot)
        # CONFIRM_DATA means we're confirming delivery data before showing payment
        phase_map = {
            "THANK_YOU": "UPSELL_OFFERED",
            "SHOW_PAYMENT": "WAITING_FOR_PAYMENT_PROOF",  # Waiting for screenshot/proof
            "CONFIRM_DATA": "WAITING_FOR_PAYMENT_METHOD",  # Confirming data, then show payment
            "REQUEST_DATA": "WAITING_FOR_DELIVERY_DATA",  # Still collecting delivery data
        }
        mapped_phase = phase_map.get(payment_sub_phase, "WAITING_FOR_DELIVERY_DATA")
        
        # Additional check: if user says "оплатила" but sub-phase wasn't updated yet,
        # force WAITING_FOR_PAYMENT_PROOF
        # (This is a safety net - ideally get_payment_sub_phase should catch this)
        if payment_sub_phase == "SHOW_PAYMENT":
            return "WAITING_FOR_PAYMENT_PROOF"
        
        return mapped_phase

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
# SINGLE SOURCE OF TRUTH: Use INTENT_PATTERNS from intent.py
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
        from src.agents.langgraph.nodes.intent import INTENT_PATTERNS

        _INTENT_PATTERNS_CACHE = INTENT_PATTERNS
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
        "REQUEST_PHOTO",  # Before THANKYOU to catch "покажи фото"
        "PRODUCT_CATEGORY",
        "THANKYOU_SMALLTALK",  # Last - catch "дякую", "ок" at end
    ]

    for intent in priority_intents:
        keywords = patterns.get(intent, [])
        for keyword in keywords:
            if keyword in message_lower:
                return intent

    return None


# Legacy alias for backward compatibility
INTENT_KEYWORDS = {}  # Deprecated - use _get_intent_patterns() instead
