"""Parser for extracting client data from message text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.services.core.client_parser_config import (
    get_client_parser_list,
    get_client_parser_value,
)


@dataclass
class ClientData:
    """Extracted client information."""

    full_name: str | None = None
    phone: str | None = None
    city: str | None = None
    nova_poshta: str | None = None

    def is_complete(self) -> bool:
        """Check if all required fields are filled."""
        return all([self.full_name, self.phone, self.city, self.nova_poshta])

    def to_dict(self) -> dict:
        """Convert to dictionary for ManyChat fields."""
        return {
            "client_name": self.full_name or "",
            "client_phone": self.phone or "",
            "client_city": self.city or "",
            "client_nova_poshta": self.nova_poshta or "",
        }


PHONE_PATTERNS = get_client_parser_list("phone_patterns") or [
    r"\+?380\s*\d{2}\s*\d{3}\s*\d{2}\s*\d{2}",
    r"0\d{2}\s*\d{3}\s*\d{2}\s*\d{2}",
    r"0\d{2}\s+\d{3}\s+\d{2}\s+\d{2}",
    r"0\d{2}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}",
]

NP_PATTERNS = get_client_parser_list("np_patterns")
NP_KEYWORDS = get_client_parser_list("np_keywords")
UKRAINIAN_CITIES = get_client_parser_list("cities")
CITY_PATTERNS = get_client_parser_list("city_patterns")

NAME_PATTERN = get_client_parser_value(
    "name_pattern",
    r"([\u0410-\u042F\u0406\u0407\u0404\u0490][\u0430-\u044F\u0456\u0457\u0454\u0491']+(?:\s+[\u0410-\u042F\u0406\u0407\u0404\u0490][\u0430-\u044F\u0456\u0457\u0454\u0491']+){1,2})",
)


def normalize_phone(phone: str) -> str:
    """Normalize phone number to +380XXXXXXXXX format."""
    digits = re.sub(r"\D", "", phone)

    if digits.startswith("380") and len(digits) == 12:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 10:
        return f"+38{digits}"
    if len(digits) == 9:
        return f"+380{digits}"

    return phone


def extract_phone(text: str) -> str | None:
    """Extract phone number from text."""
    text_lower = text.lower()

    for pattern in PHONE_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            return normalize_phone(match.group(0))

    return None


def extract_nova_poshta(text: str) -> str | None:
    """Extract Nova Poshta branch number from text."""
    text_lower = text.lower()

    for pattern in NP_PATTERNS:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            match = compiled.search(text_lower)
            if match:
                return match.group(1)
        except re.error:
            # Skip invalid patterns
            continue

    if any(word in text_lower for word in NP_KEYWORDS):
        numbers = re.findall(r"\b(\d{1,4})\b", text)
        for num in numbers:
            if 1 <= int(num) <= 9999:
                return num

    return None


def extract_city(text: str) -> str | None:
    """Extract city name from text."""
    text_lower = text.lower()

    for city in UKRAINIAN_CITIES:
        if city in text_lower:
            return city.title()

    for pattern in CITY_PATTERNS:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            match = compiled.search(text)
            if match:
                return match.group(1).strip().title()
        except re.error:
            # Skip invalid patterns
            continue

    return None


def extract_full_name(text: str) -> str | None:
    """Extract full name from text."""
    clean_text = text
    for pattern in PHONE_PATTERNS:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            clean_text = compiled.sub("", clean_text)
        except re.error:
            # Skip invalid patterns
            continue

    matches = re.findall(NAME_PATTERN, clean_text)

    for match in matches:
        words = match.split()
        if len(words) >= 2:
            is_city = any(word.lower() in " ".join(UKRAINIAN_CITIES) for word in words)
            if not is_city:
                return match.strip()

    return None


def parse_client_data(text: str) -> ClientData:
    """Parse all client data from a message text."""
    return ClientData(
        full_name=extract_full_name(text),
        phone=extract_phone(text),
        city=extract_city(text),
        nova_poshta=extract_nova_poshta(text),
    )
