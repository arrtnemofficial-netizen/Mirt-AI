"""
Payment Flow FSM - Pure functions for payment sub-phases.
==========================================================

This module extracts payment logic from agent_node into clean,
testable functions. Each sub-phase is handled by a dedicated function.

Sub-phases (matching state_prompts.py):
1. REQUEST_DATA - Collecting customer delivery data (no data yet)
2. CONFIRM_DATA - All data collected, asking for payment method choice
3. SHOW_PAYMENT - Payment method chosen, showing requisites, waiting for screenshot
4. THANK_YOU - Payment confirmed, ready for fulfillment

Architecture:
- Pure functions with explicit inputs/outputs
- No global state, no side effects (except logging)
- Easy to unit test each sub-phase
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.agents.pydantic.models import MessageItem
from src.conf.payment_config import (
    PAYMENT_DEFAULT_PRICE,
    PAYMENT_PREPAY_AMOUNT,
    format_requisites_multiline,
)
from src.core.state_machine import State


logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class PaymentFlowResult:
    """Result of payment sub-phase processing."""

    messages: list[MessageItem]
    next_sub_phase: str
    next_state: str
    event: str
    metadata_updates: dict[str, Any]

    # For escalation after payment complete
    should_escalate: bool = False
    escalation_reason: str | None = None


@dataclass
class CustomerData:
    """Extracted customer delivery data."""

    name: str | None = None
    phone: str | None = None
    city: str | None = None
    nova_poshta: str | None = None

    @property
    def is_complete(self) -> bool:
        """Check if all required fields are filled."""
        return all([self.name, self.phone, self.city, self.nova_poshta])


# =============================================================================
# KEYWORD LISTS (centralized)
# =============================================================================

FULL_PAYMENT_KEYWORDS = [
    "повна", "повну", "повної", "повністю",
    "на фоп", "фоп", "без комісії", "без комісій"
]

PREPAY_KEYWORDS = [
    "передплат", "частин", "залишок",
    "накладен", "при отриманні", "решта",
    "на нп", "оплата на нп", "решту на нп",  # "на НП" = накладений платіж
]
# NOTE: Use "на нп" instead of just "нп" to avoid matching "НП 54" (branch number)

PAYMENT_CONFIRM_KEYWORDS = [
    "оплатил", "оплатила", "сплатил", "сплатила",
    "відправив", "відправила", "переказал", "переказала",
    "надіслав", "надіслала", "скрін", "готово", "done"
]

SIZE_CHART_KEYWORDS = [
    "розмірну сітку", "розмірна сітка",
    "размерную сетку", "размерная сетка",
    "таблиця розмірів"
]


# =============================================================================
# SUB-PHASE HANDLERS
# =============================================================================


def handle_request_data(
    customer_data: CustomerData,
    session_id: str,
) -> PaymentFlowResult:
    """
    Handle REQUEST_DATA sub-phase.
    
    When all data is collected, transition to CONFIRM_DATA.
    """
    if not customer_data.is_complete:
        # Still missing data - this shouldn't happen if LLM parsed correctly
        return PaymentFlowResult(
            messages=[
                MessageItem(content="Будь ласка, надайте ПІБ, телефон, місто та відділення НП 📝")
            ],
            next_sub_phase="REQUEST_DATA",
            next_state=State.STATE_5_PAYMENT_DELIVERY.value,
            event="simple_answer",
            metadata_updates={},
        )

    # All data collected - show summary and ask about payment method
    logger.info("💰 [SESSION %s] Payment FSM: REQUEST_DATA → CONFIRM_DATA", session_id)

    return PaymentFlowResult(
        messages=[
            MessageItem(content="Записала дані 📝"),
            MessageItem(content=f"Отримувач: {customer_data.name}"),
            MessageItem(content=f"Телефон: {customer_data.phone}"),
            MessageItem(content=f"Доставка: {customer_data.city}, НП {customer_data.nova_poshta}"),
            MessageItem(
                content=(
                    "Як зручніше оплатити?\n"
                    f"✅ Повна оплата на ФОП (без комісій)\n"
                    f"✅ Передплата {PAYMENT_PREPAY_AMOUNT} грн (решта на НП)"
                )
            ),
        ],
        next_sub_phase="CONFIRM_DATA",
        next_state=State.STATE_5_PAYMENT_DELIVERY.value,
        event="simple_answer",
        metadata_updates={
            # NOTE: DO NOT set delivery_data_confirmed=True here!
            # That would skip CONFIRM_DATA and go straight to SHOW_PAYMENT.
            # We set it AFTER user chooses payment method.
            "customer_name": customer_data.name,
            "customer_phone": customer_data.phone,
            "customer_city": customer_data.city,
            "customer_nova_poshta": customer_data.nova_poshta,
        },
    )


def handle_confirm_data(
    user_text: str,
    product_price: int,
    product_size: str | None,
    session_id: str,
) -> PaymentFlowResult:
    """
    Handle CONFIRM_DATA sub-phase.
    
    Detect payment method choice and show requisites.
    """
    user_text_lower = user_text.lower()

    is_full = any(kw in user_text_lower for kw in FULL_PAYMENT_KEYWORDS)
    is_prepay = any(kw in user_text_lower for kw in PREPAY_KEYWORDS)
    ask_size_chart = any(kw in user_text_lower for kw in SIZE_CHART_KEYWORDS)

    # If price not available, use fallback
    price = product_price if product_price > 0 else PAYMENT_DEFAULT_PRICE

    if is_full or is_prepay:
        payment_method = "full" if is_full else "prepay"
        payment_amount = price if is_full else PAYMENT_PREPAY_AMOUNT

        requisites_text = format_requisites_multiline()

        messages = [
            MessageItem(content=f"Супер! Сума до сплати: {payment_amount} грн 💳"),
            MessageItem(content="Реквізити для оплати:"),
            MessageItem(content=requisites_text),
            MessageItem(content="Після оплати надішліть скрін квитанції 🌸"),
        ]

        # If user also asked for size chart
        if ask_size_chart and product_size:
            messages.append(MessageItem(
                content=(
                    f"По розмірній сітці під цей костюм зараз радимо розмір {product_size}. "
                    "Ми підбираємо розмір за зростом так, щоб був невеликий запас по довжині."
                )
            ))

        logger.info(
            "💰 [SESSION %s] Payment FSM: CONFIRM_DATA → SHOW_PAYMENT (method=%s, amount=%d)",
            session_id, payment_method, payment_amount
        )

        return PaymentFlowResult(
            messages=messages,
            next_sub_phase="SHOW_PAYMENT",
            next_state=State.STATE_5_PAYMENT_DELIVERY.value,
            event="simple_answer",
            metadata_updates={
                "delivery_data_confirmed": True,  # NOW we confirm data + payment method
                "payment_method": payment_method,
                "payment_amount": payment_amount,
            },
        )

    # User said something else - clarify
    return PaymentFlowResult(
        messages=[
            MessageItem(
                content=(
                    f"Підкажіть, як зручніше оплатити - повна оплата чи "
                    f"передплата {PAYMENT_PREPAY_AMOUNT} грн? 🤍"
                )
            ),
        ],
        next_sub_phase="CONFIRM_DATA",
        next_state=State.STATE_5_PAYMENT_DELIVERY.value,
        event="simple_answer",
        metadata_updates={},
    )


def handle_show_payment(
    user_text: str,
    has_image: bool,
    session_id: str,
) -> PaymentFlowResult:
    """
    Handle SHOW_PAYMENT sub-phase.
    
    Detect payment confirmation (text or screenshot) and complete.
    """
    user_text_lower = user_text.lower()

    is_confirmed = any(kw in user_text_lower for kw in PAYMENT_CONFIRM_KEYWORDS)

    if is_confirmed or has_image:
        logger.info("💰 [SESSION %s] Payment FSM: SHOW_PAYMENT → THANK_YOU", session_id)

        return PaymentFlowResult(
            messages=[
                MessageItem(content="Дякую за оплату! 🎉"),
                MessageItem(
                    content="Замовлення прийнято. Передаю менеджеру для формування відправки."
                ),
                MessageItem(content="Як буде трек-номер — напишемо вам 🤍"),
            ],
            next_sub_phase="THANK_YOU",
            next_state=State.STATE_7_END.value,
            event="escalation",
            metadata_updates={
                "payment_proof_received": True,
                "payment_confirmed": True,
            },
            should_escalate=True,
            escalation_reason="ORDER_CONFIRMED_ASSIGN_MANAGER",
        )

    # Still waiting
    return PaymentFlowResult(
        messages=[
            MessageItem(content="Чекаю скрін оплати 🌸"),
        ],
        next_sub_phase="SHOW_PAYMENT",
        next_state=State.STATE_5_PAYMENT_DELIVERY.value,
        event="simple_answer",
        metadata_updates={},
    )


# =============================================================================
# MAIN DISPATCHER
# =============================================================================


def process_payment_subphase(
    sub_phase: str,
    user_text: str,
    has_image: bool,
    customer_data: CustomerData,
    product_price: int,
    product_size: str | None,
    session_id: str,
) -> PaymentFlowResult:
    """
    Main dispatcher for payment sub-phase processing.
    
    Routes to appropriate handler based on current sub-phase.
    
    Args:
        sub_phase: Current payment sub-phase
        user_text: User's message text (lowercase)
        has_image: Whether user sent an image
        customer_data: Extracted customer delivery data
        product_price: Price of selected product(s)
        product_size: Size of selected product (for size chart requests)
        session_id: Session identifier for logging
        
    Returns:
        PaymentFlowResult with messages, state updates, and metadata
    """
    if sub_phase == "REQUEST_DATA":
        return handle_request_data(customer_data, session_id)

    elif sub_phase == "CONFIRM_DATA":
        return handle_confirm_data(user_text, product_price, product_size, session_id)

    elif sub_phase == "SHOW_PAYMENT":
        return handle_show_payment(user_text, has_image, session_id)

    elif sub_phase == "THANK_YOU":
        # Already complete - shouldn't happen normally
        return PaymentFlowResult(
            messages=[MessageItem(content="Ваше замовлення вже оформлено 🤍")],
            next_sub_phase="THANK_YOU",
            next_state=State.STATE_7_END.value,
            event="simple_answer",
            metadata_updates={},
        )

    else:
        # Unknown sub-phase - start from beginning
        logger.warning("Unknown payment sub-phase: %s", sub_phase)
        return PaymentFlowResult(
            messages=[
                MessageItem(content="Будь ласка, надайте дані для доставки 📝")
            ],
            next_sub_phase="REQUEST_DATA",
            next_state=State.STATE_5_PAYMENT_DELIVERY.value,
            event="simple_answer",
            metadata_updates={},
        )


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def extract_customer_data_from_state(state: dict[str, Any]) -> CustomerData:
    """
    Extract customer data from state.
    
    Checks both metadata and root-level keys.
    """
    metadata = state.get("metadata", {})

    return CustomerData(
        name=metadata.get("customer_name") or state.get("customer_name"),
        phone=metadata.get("customer_phone") or state.get("customer_phone"),
        city=metadata.get("customer_city") or state.get("customer_city"),
        nova_poshta=metadata.get("customer_nova_poshta") or state.get("customer_nova_poshta"),
    )


def get_product_info_from_state(state: dict[str, Any]) -> tuple[int, str | None]:
    """
    Extract product price and size from state.
    
    Returns:
        (price, size) tuple
    """
    products = state.get("selected_products", [])
    if not products:
        products = state.get("offered_products", [])

    if products:
        first_product = products[0]
        price = first_product.get("price", 0)
        size = first_product.get("size")
        return price, size

    return 0, None
