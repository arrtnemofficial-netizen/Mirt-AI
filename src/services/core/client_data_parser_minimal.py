"""Minimal client data parser - only phone and NP number."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.services.core.client_parser_config import get_client_parser_list


@dataclass
class MinimalClientData:
    """Minimal extracted client data (phone + NP only)."""

    phone: str | None = None
    nova_poshta: str | None = None


def extract_phone(text: str) -> str | None:
    """Extract and normalize Ukrainian phone number."""
    patterns = get_client_parser_list("phone_patterns") or [
        r"\+?380\s*\d{2}\s*\d{3}\s*\d{2}\s*\d{2}",
        r"0\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            digits = re.sub(r"\D", "", match.group(0))
            if digits.startswith("380") and len(digits) == 12:
                return f"+{digits}"
            if digits.startswith("0") and len(digits) == 10:
                return f"+38{digits}"

    return None


def extract_nova_poshta(text: str) -> str | None:
    """Extract Nova Poshta branch number."""
    text_lower = text.lower()
    patterns = get_client_parser_list("np_patterns")

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            return match.group(1)

    return None


def parse_minimal(text: str) -> MinimalClientData:
    """Parse only phone and NP from text."""
    return MinimalClientData(
        phone=extract_phone(text),
        nova_poshta=extract_nova_poshta(text),
    )
