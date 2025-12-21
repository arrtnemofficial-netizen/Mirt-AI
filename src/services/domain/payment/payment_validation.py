"""
Payment Validation Service.
===========================
Single Source of Truth (SSOT) for:
- Phone number normalization
- Delivery data completeness check
- Payment proof detection
- Payment sub-phase determination
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.services.domain.payment.payment_config import get_payment_list, get_payment_section

logger = logging.getLogger(__name__)


def validate_phone_number(phone: str) -> str | None:
    """
    Validate and normalize phone number.
    Returns +380XXXXXXXXX if valid, None otherwise.
    """
    if not phone:
        return None
        
    # Remove all non-digits
    digits = re.sub(r"\D", "", phone)
    
    # Check length and prefix
    if len(digits) == 12 and digits.startswith("380"):
        return f"+{digits}"
    
    if len(digits) == 10 and digits.startswith("0"):
        return f"+38{digits}"
        
    if len(digits) == 9:
        return f"+380{digits}"
        
    return None


def detect_payment_proof(text: str, has_image: bool = False) -> bool:
    """
    Detect if the user is providing payment proof.
    """
    if has_image:
        return True

    proof_keywords = get_payment_list("validation", "payment_proof_keywords")
    if not proof_keywords:
        proof_keywords = ["paid", "payment", "transfer", "receipt"]

    text_lower = (text or "").lower()
    return any(kw in text_lower for kw in proof_keywords)


def is_order_ready(metadata: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Check if order has all required delivery fields.
    Returns (is_ready, missing_fields_list).
    """
    labels = get_payment_section("validation").get("required_fields", {})
    required = {
        "customer_name": labels.get("customer_name", "Full name"),
        "customer_phone": labels.get("customer_phone", "Phone"),
        "customer_city": labels.get("customer_city", "City"),
        "customer_nova_poshta": labels.get("customer_nova_poshta", "Branch"),
    }
    
    missing = []
    for key, label in required.items():
        if not metadata.get(key):
            missing.append(label)
            
    return len(missing) == 0, missing


def get_payment_sub_phase(metadata: dict[str, Any]) -> str:
    """
    Determine the current sub-phase of the payment flow.
    SSOT for sub-phase transitions.
    """
    # Check completeness
    is_ready, _ = is_order_ready(metadata)
    
    # Status flags
    data_confirmed = metadata.get("delivery_data_confirmed", False)
    payment_proof = metadata.get("payment_proof_received", False)

    if payment_proof:
        return "THANK_YOU"
    elif data_confirmed:
        return "SHOW_PAYMENT"
    elif is_ready:
        return "CONFIRM_DATA"
    else:
        return "REQUEST_DATA"
