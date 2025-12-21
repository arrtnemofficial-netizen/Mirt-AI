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

import re
import logging
from typing import Any

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
        
    from src.core.prompt_registry import get_snippet_by_header
    import json
    labels_json = get_snippet_by_header("VISION_LABELS")
    labels = json.loads(labels_json[0]) if labels_json else {}
    
    proof_keywords = labels.get("payment_proof_keywords", [
        "оплатив", "оплатила", "скинув", "скинула", "чек", 
        "оплачено", "переказав", "переказала", "готов", "сплатив"
    ])
    
    text_lower = (text or "").lower()
    return any(kw in text_lower for kw in proof_keywords)


def is_order_ready(metadata: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Check if order has all required delivery fields.
    Returns (is_ready, missing_fields_list).
    """
    required = {
        "customer_name": "ПІБ",
        "customer_phone": "Телефон",
        "customer_city": "Місто",
        "customer_nova_poshta": "Відділення НП"
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
