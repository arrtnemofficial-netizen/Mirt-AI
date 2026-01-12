"""
Agent Post-processing Helpers.
==============================
Handles logic AFTER LLM execution:
- Cart merging (using CartService)
- Fallback parsing (Size/Color extraction)
- State transition overrides (SSOT)
- Metadata updates
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.core.state_machine import State
from src.core.intents import INTENT_PATTERNS
from src.agents.langgraph.rules.cart_intent import detect_add_to_cart
from src.agents.langgraph.fsm.transition_reducer import compute_transition, derive_dialog_phase
from src.agents.langgraph.state_prompts import determine_next_dialog_phase, get_payment_sub_phase
from src.agents.langgraph.nodes.helpers.size_parsing import extract_size_from_response, height_to_size
from src.agents.langgraph.nodes.utils import extract_height_from_text
from src.services.cart import CartManager
from src.services.observability import track_metric

logger = logging.getLogger(__name__)


def apply_ssot_state_transition(
    state: dict[str, Any],
    llm_response_state: str,
    llm_intent: str,
    user_message: str,
) -> tuple[str, str]:
    """
    Apply SSOT Reducer logic to override LLM state/intent if needed.
    Returns (final_state, final_intent).
    """
    session_id = state.get("session_id", "")
    current_state = state.get("current_state", "")

    # Global priorities - do not override
    global_priority_intents = {"COMPLAINT", "PHOTO_IDENT"}
    if llm_intent in global_priority_intents:
        return llm_response_state, llm_intent

    # Check for preserved payment state
    payment_context = state.get("_payment_context", {})
    if payment_context.get("preserve_state", False) and current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        logger.info("[SESSION %s] 🛡️ Preserving STATE_5_PAYMENT_DELIVERY", session_id)
        return State.STATE_5_PAYMENT_DELIVERY.value, llm_intent

    # Run Reducer
    has_image = state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
    transition = compute_transition(
        state=state,
        intent=llm_intent or "DISCOVERY_OR_QUESTION",
        has_image=has_image,
        user_message=user_message,
    )

    final_state = llm_response_state
    final_intent = llm_intent

    if transition.next_state != llm_response_state:
        logger.info(
            "[SESSION %s] SSOT Override: LLM state=%s -> SSOT state=%s",
            session_id, llm_response_state, transition.next_state
        )
        final_state = transition.next_state

        # Ensure correct intent for payment transition
        if final_state == State.STATE_5_PAYMENT_DELIVERY.value and final_intent != "PAYMENT_DELIVERY":
            final_intent = "PAYMENT_DELIVERY"

    return final_state, final_intent


def update_cart_and_products(
    state: dict[str, Any],
    llm_products: list[Any],  # Pydantic models
    user_message: str,
    current_state: str,
) -> list[dict[str, Any]]:
    """
    Update cart using CartService.
    Handles explicit add intent in payment flow.
    """
    session_id = state.get("session_id", "")
    selected_products = state.get("selected_products", []) or []

    if not llm_products:
        return selected_products

    # Convert Pydantic models to dicts
    new_products_dicts = [p.model_dump() for p in llm_products]

    is_payment_state = current_state == State.STATE_5_PAYMENT_DELIVERY.value
    has_explicit_add = detect_add_to_cart(user_message.lower())

    cart_manager = CartManager(session_id=session_id)

    # Logic:
    # - In Payment State: Only add if explicit intent. Otherwise ignore LLM products (anti-hallucination).
    # - In Other States: Merge normally.

    if is_payment_state:
        if has_explicit_add:
            updated_cart, added = cart_manager.add_products(
                selected_products, new_products_dicts, strategy="strict"
            )
            logger.info("Payment State: Added %d products (explicit intent)", added)
            return updated_cart
        else:
            logger.info("Payment State: Ignored LLM products (no add intent)")
            return selected_products

    # Normal merge
    updated_cart, added = cart_manager.add_products(
        selected_products, new_products_dicts, strategy="strict"
    )
    return updated_cart


def fallback_parsing_logic(
    state: dict[str, Any],
    products: list[dict[str, Any]],
    user_message: str,
    llm_messages: list[Any],
) -> list[dict[str, Any]]:
    """
    Perform fallback extraction of size/color if missing in structured products.
    """
    if not products:
        return products

    session_id = state.get("session_id", "")
    current_state = state.get("current_state", "")

    # Only relevant in SIZE_COLOR state
    if current_state != State.STATE_3_SIZE_COLOR.value:
        return products

    updated = list(products)
    first_product = updated[0]
    fallback_used = False
    reasons = []

    # 1. Size from user height (e.g. "98")
    if not first_product.get("size"):
        height_cm = extract_height_from_text(user_message)
        if height_cm:
            extracted = height_to_size(height_cm)
            first_product["size"] = extracted
            fallback_used = True
            reasons.append("size_from_user_height")

    # 2. Size from LLM text (if LLM forgot to put in JSON)
    if not first_product.get("size"):
        extracted = extract_size_from_response(llm_messages)
        if extracted:
            first_product["size"] = extracted
            fallback_used = True
            reasons.append("size_from_llm_response")

    # 3. Color from vision state
    if not first_product.get("color") and state.get("identified_color"):
        first_product["color"] = state.get("identified_color")
        fallback_used = True
        reasons.append("color_from_vision")

    if fallback_used:
        track_metric(
            "llm_fallback_parsing_used",
            1,
            {"session_id": session_id, "state": current_state, "reasons": ",".join(reasons)}
        )

    updated[0] = first_product
    return updated


def determine_final_dialog_phase(
    current_state: str,
    event: str,
    intent: str,
    products: list[dict[str, Any]],
    metadata: dict[str, Any],
    state: dict[str, Any],
) -> str:
    """
    Determine next dialog phase using state prompts logic.
    """
    if event == "escalation":
        return "COMPLETED"

    has_products = bool(products)
    has_size = False
    has_color = False

    if products:
        p = products[0]
        has_size = bool(p.get("size"))
        has_color = bool(p.get("color"))
        # Fallback: color in name
        if not has_color and "(" in p.get("name", ""):
            has_color = True

    user_confirmed = event == "simple_answer" and intent == "PAYMENT_DELIVERY"

    payment_sub_phase = None
    if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        payment_sub_phase = get_payment_sub_phase(state)

    return determine_next_dialog_phase(
        current_state=current_state,
        intent=intent,
        has_products=has_products,
        has_size=has_size,
        has_color=has_color,
        user_confirmed=user_confirmed,
        payment_sub_phase=payment_sub_phase,
    )
