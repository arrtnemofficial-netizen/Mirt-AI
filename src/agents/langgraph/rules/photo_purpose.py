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
        # Check for product addition intent across ALL transactional phases
        from src.agents.langgraph.rules.payment_proof import detect_payment_proof
        from src.agents.langgraph.rules.product_addition import detect_product_addition_intent

        is_product_addition = detect_product_addition_intent(user_message)
        is_payment_proof = detect_payment_proof(
            user_text=user_message,
            has_image=True,
            has_url=False,
        )

        # КРИТИЧНО: Якщо це явний product addition intent - route to vision
        if is_product_addition and not is_payment_proof:
            return ("product_ident", "product_addition_intent_in_payment_phase")

        # КРИТИЧНО: Якщо фото БЕЗ тексту або з мінімальним текстом БЕЗ даних доставки - це новий товар!
        # Перевіряємо, чи є в тексті дані доставки (ПІБ, телефон, місто, НП)
        has_delivery_data = False
        if user_message:
            delivery_keywords = [
                "+380", "095", "050",  # Телефон
                "киев", "київ", "харьков", "одесса",  # Місто
                "нп", "відділення", "поштомат",  # НП
            ]
            # Перевіряємо наявність ПІБ (ім'я з великої літери або кілька слів)
            import re
            # ПІБ зазвичай містить 2-3 слова з великої літери
            has_name = bool(re.search(r'\b[А-ЯІЇЄЁ][а-яіїєё]+(?:\s+[А-ЯІЇЄЁ][а-яіїєё]+){1,2}\b', user_message))
            has_delivery_keywords = any(kw in user_message_lower for kw in delivery_keywords)
            has_delivery_data = has_name or has_delivery_keywords

        # Якщо фото БЕЗ даних доставки та БЕЗ keywords оплати - це новий товар!
        if not has_delivery_data and not is_payment_proof:
            # Це фото нового товара - треба розпізнати через vision і спитати "оформляємо?"
            logger.info(
                "Photo in STATE_5 without delivery data or payment keywords - treating as new product (route to vision)"
            )
            return ("product_ident", "new_product_photo_in_payment_phase")

        # Якщо є дані доставки або keywords оплати - це transactional (payment proof або контекст)
        # Default for transactional phases: payment proof or context
        return ("transactional", f"transactional_phase_{dialog_phase}")

    # =========================================================================
    # PRIORITY 3: First photo in session (INIT/DISCOVERY)
    # =========================================================================
    if not vision_greeted and dialog_phase in vision_allowed_phases:
        return ("product_ident", "first_photo_in_session")

    # =========================================================================
    # PRIORITY 4: Smart rerun vision (mid-conversation)
    # =========================================================================
    # If no product selected AND user asks for price/model → run vision
    # But if product IS selected → user is asking about THAT product, not a new one
    if phase_aware_enabled and vision_greeted and dialog_phase not in vision_allowed_phases:
        # Check if user asks for price/model identification
        price_model_keywords = [
            "цена", "ціна", "price",
            "что за модель", "що за модель", "яка модель",
            "что это", "що це", "what is this",
        ]

        asks_for_identification = any(
            keyword in user_message_lower for keyword in price_model_keywords
        )

        # Smart rerun ONLY if:
        # 1. No products selected at all (need to identify) OR
        # 2. User explicitly asks "what is this" type questions AND no product in context
        if not selected_products and asks_for_identification:
            return ("product_ident", "smart_rerun_no_products_or_asks_identification")

        # If products are already selected, questions about price/size are about THOSE products
        # Handle in context (agent will answer from product data)
        return ("context", f"mid_conversation_phase_{dialog_phase}")

    # =========================================================================
    # PRIORITY 5: Phase-aware disabled or fallback
    # =========================================================================
    if not phase_aware_enabled:
        return ("product_ident", "phase_aware_disabled")

    # Default fallback: context
    return ("context", f"fallback_phase_{dialog_phase}")

