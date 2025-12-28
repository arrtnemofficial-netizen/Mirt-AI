"""
Photo Purpose Detection - Single Source of Truth.
==================================================
Determines how to handle an incoming photo:
- product_ident: Route to vision for product identification
- transactional: Route to payment (payment proof)
- context: Handle in current agent context
"""

from __future__ import annotations

import logging
from typing import Literal

from src.conf.config import settings

logger = logging.getLogger(__name__)

PhotoPurpose = Literal["product_ident", "transactional", "context"]


def determine_photo_purpose(
    state: dict,
    user_message: str | None = None,
) -> tuple[PhotoPurpose, str]:
    """
    Determine photo purpose based on state and user message.
    
    This is the SINGLE SOURCE OF TRUTH for photo routing decisions.
    Used by both master_router and intent_detection_node.
    
    Args:
        state: Current conversation state
        user_message: User's message text (optional, extracted if not provided)
    
    Returns:
        Tuple of (purpose, reason) where:
        - purpose: "product_ident" | "transactional" | "context"
        - reason: Human-readable reason for logging/metrics
    """
    metadata = state.get("metadata", {}) or {}
    dialog_phase = state.get("dialog_phase", "INIT")
    vision_greeted = bool(metadata.get("vision_greeted", False))
    selected_products = state.get("selected_products", []) or []
    
    # Extract user message if not provided
    if user_message is None:
        from src.agents.langgraph.nodes.utils import extract_user_message
        user_message = extract_user_message(state.get("messages", [])) or ""
    
    user_message_lower = user_message.lower() if user_message else ""
    
    # Phases where vision is allowed (first photo scenarios)
    vision_allowed_phases = {"INIT", "DISCOVERY"}
    
    # Transactional phases where images should be interpreted as payment proof
    transactional_phases = {
        "WAITING_FOR_PAYMENT_PROOF",
        "WAITING_FOR_PAYMENT_METHOD",
        "WAITING_FOR_DELIVERY_DATA",
    }
    
    # =========================================================================
    # PRIORITY 1: Explicit "new product" trigger
    # =========================================================================
    if user_message:
        from src.agents.langgraph.nodes.helpers.policy_snippets import detect_explicit_new_product
        
        if detect_explicit_new_product(user_message, state):
            return ("product_ident", "explicit_new_product_trigger")
    
    # =========================================================================
    # PRIORITY 2: Product addition intent in transactional phases
    # =========================================================================
    phase_aware_enabled = getattr(settings, "PHASE_AWARE_IMAGE_ROUTING", True)
    
    if phase_aware_enabled and dialog_phase in transactional_phases:
        if user_message and dialog_phase == "WAITING_FOR_PAYMENT_PROOF":
            from src.agents.langgraph.rules.product_addition import detect_product_addition_intent
            from src.agents.langgraph.rules.payment_proof import detect_payment_proof
            
            is_product_addition = detect_product_addition_intent(user_message)
            is_payment_proof = detect_payment_proof(
                user_text=user_message,
                has_image=True,
                has_url=False,
            )
            
            if is_product_addition and not is_payment_proof:
                return ("product_ident", "product_addition_intent_in_payment_phase")
        
        # Default for transactional phases: payment proof
        return ("transactional", f"transactional_phase_{dialog_phase}")
    
    # =========================================================================
    # PRIORITY 3: First photo in session (INIT/DISCOVERY)
    # =========================================================================
    if not vision_greeted and dialog_phase in vision_allowed_phases:
        return ("product_ident", "first_photo_in_session")
    
    # =========================================================================
    # PRIORITY 4: Smart rerun vision (mid-conversation)
    # =========================================================================
    # If no product selected OR user explicitly asks for price/model
    if phase_aware_enabled and vision_greeted and dialog_phase not in vision_allowed_phases:
        # Check if user asks for price/model identification
        price_model_keywords = [
            "цена", "ціна", "price",
            "что за модель", "що за модель", "яка модель",
            "что это", "що це", "what is this",
            "модель", "model",
        ]
        
        asks_for_identification = any(
            keyword in user_message_lower for keyword in price_model_keywords
        )
        
        # Smart rerun: if no products selected OR user asks for identification
        if not selected_products or asks_for_identification:
            return ("product_ident", "smart_rerun_no_products_or_asks_identification")
        
        # Otherwise: handle in context
        return ("context", f"mid_conversation_phase_{dialog_phase}")
    
    # =========================================================================
    # PRIORITY 5: Phase-aware disabled or fallback
    # =========================================================================
    if not phase_aware_enabled:
        return ("product_ident", "phase_aware_disabled")
    
    # Default fallback: context
    return ("context", f"fallback_phase_{dialog_phase}")

