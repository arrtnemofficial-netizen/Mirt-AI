"""Minimal client data parser - only phone and NP number.

Names and cities should be handled by LLM with proper prompting.
This parser extracts ONLY reliably regex-able data:
- Phone numbers (strict format)
- Nova Poshta branch numbers
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class MinimalClientData:
    """Minimal extracted client data (phone + NP only)."""

    phone: str | None = None
    nova_poshta: str | None = None


def extract_phone(text: str) -> str | None:
    """Extract and normalize Ukrainian phone number.
    
    Returns: +380XXXXXXXXX or None
    """
    # Pattern: +380, 380, 0XX formats
    patterns = [
        r"\+?380\s*\d{2}\s*\d{3}\s*\d{2}\s*\d{2}",  # +380951234567
        r"0\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",  # 095 123 45 67
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            # Normalize to +380...
            digits = re.sub(r"\D", "", match.group(0))
            if digits.startswith("380") and len(digits) == 12:
                return f"+{digits}"
            elif digits.startswith("0") and len(digits) == 10:
                return f"+38{digits}"

    return None


def extract_nova_poshta(text: str) -> str | None:
    """Extract Nova Poshta branch number.
    
    Handles: НП 54, нп54, відділення 25, поштомат 100, нова почта 15
    Returns: Just the number (string)
    """
    text_lower = text.lower()

    # Patterns ordered by specificity
    patterns = [
        r"(?:нп|np)\s*[№#]?\s*(\d{1,4})",  # НП 54, нп54
        r"(?:відділення|отделение)\s*[№#]?\s*(\d{1,4})",  # відділення 25
        r"(?:поштомат|почтомат)\s*[№#]?\s*(\d{1,4})",  # поштомат 100
        r"(?:нова\s*пошта|новая\s*почта)\s*[№#]?\s*(\d{1,4})",  # нова пошта 15
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            return match.group(1)

    return None


def parse_minimal(text: str) -> MinimalClientData:
    """Parse only phone and NP from text.
    
    For name/city normalization, rely on LLM with proper prompting.
    """
    return MinimalClientData(
        phone=extract_phone(text),
        nova_poshta=extract_nova_poshta(text),
    )
