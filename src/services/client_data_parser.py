"""Parser for extracting client data from message text."""

from __future__ import annotations

import logging
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
    logger = logging.getLogger(__name__)
    
    try:
        digits = re.sub(r"\D", "", phone)
    except re.error as e:
        logger.warning("Regex error in normalize_phone: %s (pos=%s)", str(e), getattr(e, "pos", "unknown"))
        return phone  # Return original if regex fails

    if digits.startswith("380") and len(digits) == 12:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 10:
        return f"+38{digits}"
    if len(digits) == 9:
        return f"+380{digits}"

    return phone


def extract_phone(text: str) -> str | None:
    """Extract phone number from text."""
    logger = logging.getLogger(__name__)
    text_lower = text.lower()

    for idx, pattern in enumerate(PHONE_PATTERNS):
        try:
            # Check if pattern already has inline flags (e.g., (?i) or (?i:...))
            # If pattern has inline flags, don't add re.IGNORECASE to avoid conflict
            flags = 0
            try:
                inline_flags_check = re.search(r"\(\?[iI]", pattern)
            except re.error:
                # If checking for inline flags fails, assume no inline flags
                inline_flags_check = None
            
            if not inline_flags_check:
                flags = re.IGNORECASE
            compiled = re.compile(pattern, flags)
            match = compiled.search(text_lower)
            if match:
                return normalize_phone(match.group(0))
        except re.error as e:
            logger.warning(
                "Invalid regex pattern in extract_phone[%d] (skipping): %.100s. Error: %s (pos=%s)",
                idx,
                pattern[:100] if pattern else "None",
                str(e),
                getattr(e, "pos", "unknown"),
            )
            continue

    return None


def extract_nova_poshta(text: str) -> str | None:
    """Extract Nova Poshta branch number from text."""
    logger = logging.getLogger(__name__)
    
    text_lower = text.lower()

    for idx, pattern in enumerate(NP_PATTERNS):
        
        try:
            # Check if pattern already has inline flags (e.g., (?i) or (?i:...))
            # If pattern has inline flags, don't add re.IGNORECASE to avoid conflict
            flags = 0
            try:
                inline_flags_check = re.search(r"\(\?[iI]", pattern)
            except re.error as check_err:
                inline_flags_check = None
            
            if not inline_flags_check:
                flags = re.IGNORECASE
            compiled = re.compile(pattern, flags)
            match = compiled.search(text_lower)
            if match:
                return match.group(1)
        except re.error as e:
            
            # Log problematic pattern for debugging
            logger.warning(
                "Invalid regex pattern in extract_nova_poshta (skipping): %s. Error: %s",
                pattern[:100],
                str(e)
            )
            continue

    if any(word in text_lower for word in NP_KEYWORDS):
        try:
            numbers = re.findall(r"\b(\d{1,4})\b", text)
            for num in numbers:
                if 1 <= int(num) <= 9999:
                    return num
        except re.error as e:
            logger.warning(
                "Regex error in extract_nova_poshta (findall fallback): %s (pos=%s)",
                str(e),
                getattr(e, "pos", "unknown"),
            )
            # Continue without keyword-based extraction

    return None


def extract_city(text: str) -> str | None:
    """Extract city name from text."""
    logger = logging.getLogger(__name__)
    
    text_lower = text.lower()

    for city in UKRAINIAN_CITIES:
        if city in text_lower:
            return city.title()

    for idx, pattern in enumerate(CITY_PATTERNS):
        
        try:
            # Check if pattern already has inline flags (e.g., (?i) or (?i:...))
            # If pattern has inline flags, don't add re.IGNORECASE to avoid conflict
            flags = 0
            try:
                inline_flags_check = re.search(r"\(\?[iI]", pattern)
            except re.error as check_err:
                inline_flags_check = None
            
            if not inline_flags_check:
                flags = re.IGNORECASE
            compiled = re.compile(pattern, flags)
            match = compiled.search(text)
            if match:
                return match.group(1).strip().title()
        except re.error as e:
            
            # Log problematic pattern for debugging
            logger.warning(
                "Invalid regex pattern in extract_city (skipping): %s. Error: %s",
                pattern[:100],
                str(e)
            )
            continue

    return None


def extract_full_name(text: str) -> str | None:
    """Extract full name from text."""
    logger = logging.getLogger(__name__)
    
    clean_text = text
    for idx, pattern in enumerate(PHONE_PATTERNS):
        
        try:
            # Check if pattern already has inline flags (e.g., (?i) or (?i:...))
            # If pattern has inline flags, don't add re.IGNORECASE to avoid conflict
            flags = 0
            try:
                inline_flags_check = re.search(r"\(\?[iI]", pattern)
            except re.error as check_err:
                inline_flags_check = None
            
            if not inline_flags_check:
                flags = re.IGNORECASE
            compiled = re.compile(pattern, flags)
            clean_text = compiled.sub("", clean_text)
        except re.error as e:
            
            # Log problematic pattern for debugging
            logger.warning(
                "Invalid regex pattern in extract_full_name (skipping): %s. Error: %s",
                pattern[:100],
                str(e)
            )
            continue
    
    try:
        matches = re.findall(NAME_PATTERN, clean_text)
    except re.error as e:
        
        # Log problematic pattern for debugging
        logger.warning(
            "Invalid NAME_PATTERN regex (skipping name extraction): %s. Error: %s",
            NAME_PATTERN[:100] if NAME_PATTERN else "None",
            str(e)
        )
        return None

    for match in matches:
        words = match.split()
        if len(words) >= 2:
            is_city = any(word.lower() in " ".join(UKRAINIAN_CITIES) for word in words)
            if not is_city:
                return match.strip()

    return None


def parse_client_data(text: str) -> ClientData:
    """Parse all client data from a message text."""
    logger = logging.getLogger(__name__)
    
    # Safely extract each field with individual error handling
    full_name = None
    phone = None
    city = None
    nova_poshta = None
    
    try:
        full_name = extract_full_name(text)
    except Exception as e:
        logger.warning("Failed to extract full_name: %s", str(e)[:200])
    
    try:
        phone = extract_phone(text)
    except Exception as e:
        logger.warning("Failed to extract phone: %s", str(e)[:200])
    
    try:
        city = extract_city(text)
    except Exception as e:
        logger.warning("Failed to extract city: %s", str(e)[:200])
    
    try:
        nova_poshta = extract_nova_poshta(text)
    except Exception as e:
        logger.warning("Failed to extract nova_poshta: %s", str(e)[:200])
    
    return ClientData(
        full_name=full_name,
        phone=phone,
        city=city,
        nova_poshta=nova_poshta,
    )
