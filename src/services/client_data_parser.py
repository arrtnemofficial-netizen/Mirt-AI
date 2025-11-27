"""Parser for extracting client data from message text.

Extracts:
- Full name (ПІБ)
- Phone number (Ukrainian format)
- City
- Nova Poshta branch number
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ClientData:
    """Extracted client information."""
    
    full_name: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    nova_poshta: Optional[str] = None
    
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


# ---------------------------------------------------------------------------
# Phone number patterns (Ukrainian)
# ---------------------------------------------------------------------------
PHONE_PATTERNS = [
    # +380XXXXXXXXX
    r'\+?380\s*\d{2}\s*\d{3}\s*\d{2}\s*\d{2}',
    # 0XXXXXXXXX
    r'0\d{2}\s*\d{3}\s*\d{2}\s*\d{2}',
    # 0XX XXX XX XX
    r'0\d{2}\s+\d{3}\s+\d{2}\s+\d{2}',
    # 0XX-XXX-XX-XX
    r'0\d{2}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}',
]

# ---------------------------------------------------------------------------
# Nova Poshta patterns
# ---------------------------------------------------------------------------
NP_PATTERNS = [
    # Відділення №123, відділення 123
    r'(?:відділення|віділення|отделение|№)\s*[№#]?\s*(\d{1,4})',
    # НП 123, нп №123
    r'(?:нп|np)\s*[№#]?\s*(\d{1,4})',
    # Поштомат 123
    r'(?:поштомат|почтомат)\s*[№#]?\s*(\d{1,4})',
    # Just number after city context
    r'(?:нова\s*пошта|новая\s*почта)\s*[№#]?\s*(\d{1,4})',
]

# ---------------------------------------------------------------------------
# Ukrainian cities (top 50 + common variations)
# ---------------------------------------------------------------------------
UKRAINIAN_CITIES = [
    # Major cities
    "київ", "kyiv", "kiev",
    "харків", "kharkiv", "харьков",
    "одеса", "odesa", "одесса",
    "дніпро", "dnipro", "днепр",
    "львів", "lviv", "львов",
    "запоріжжя", "zaporizhzhia", "запорожье",
    "кривий ріг", "kryvyi rih", "кривой рог",
    "миколаїв", "mykolaiv", "николаев",
    "маріуполь", "mariupol", "мариуполь",
    "вінниця", "vinnytsia", "винница",
    "херсон", "kherson",
    "полтава", "poltava",
    "чернігів", "chernihiv", "чернигов",
    "черкаси", "cherkasy", "черкассы",
    "житомир", "zhytomyr",
    "суми", "sumy",
    "рівне", "rivne", "ровно",
    "івано-франківськ", "ivano-frankivsk",
    "тернопіль", "ternopil",
    "луцьк", "lutsk",
    "кропивницький", "kropyvnytskyi",
    "ужгород", "uzhhorod",
    "чернівці", "chernivtsi", "черновцы",
    "хмельницький", "khmelnytskyi",
    # Common smaller cities
    "біла церква", "бровари", "бориспіль",
    "ірпінь", "буча", "вишгород",
    "обухів", "фастів", "васильків",
    "кам'янське", "павлоград", "нікополь",
    "мелітополь", "бердянськ", "енергодар",
]


def normalize_phone(phone: str) -> str:
    """Normalize phone number to +380XXXXXXXXX format."""
    # Remove all non-digits
    digits = re.sub(r'\D', '', phone)
    
    # Handle different formats
    if digits.startswith('380') and len(digits) == 12:
        return f"+{digits}"
    elif digits.startswith('0') and len(digits) == 10:
        return f"+38{digits}"
    elif len(digits) == 9:
        return f"+380{digits}"
    
    return phone  # Return as-is if can't normalize


def extract_phone(text: str) -> Optional[str]:
    """Extract phone number from text."""
    text_lower = text.lower()
    
    for pattern in PHONE_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            return normalize_phone(match.group(0))
    
    return None


def extract_nova_poshta(text: str) -> Optional[str]:
    """Extract Nova Poshta branch number from text."""
    text_lower = text.lower()
    
    for pattern in NP_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # Fallback: look for standalone numbers after NP-related words
    if any(word in text_lower for word in ['нп', 'пошт', 'відділ', 'отдел']):
        numbers = re.findall(r'\b(\d{1,4})\b', text)
        for num in numbers:
            if 1 <= int(num) <= 9999:  # Valid NP range
                return num
    
    return None


def extract_city(text: str) -> Optional[str]:
    """Extract city name from text."""
    text_lower = text.lower()
    
    # Check for known cities
    for city in UKRAINIAN_CITIES:
        if city in text_lower:
            # Return capitalized version
            return city.title()
    
    # Pattern: "м. Cityname" or "місто Cityname"
    city_patterns = [
        r'(?:м\.|місто|город|city)\s*([А-ЯІЇЄҐа-яіїєґA-Za-z\-\']+)',
    ]
    
    for pattern in city_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip().title()
    
    return None


def extract_full_name(text: str) -> Optional[str]:
    """Extract full name (ПІБ) from text."""
    # Remove phone numbers and known patterns first
    clean_text = text
    for pattern in PHONE_PATTERNS:
        clean_text = re.sub(pattern, '', clean_text, flags=re.IGNORECASE)
    
    # Pattern: 2-3 capitalized words (Ukrainian names)
    # Прізвище Ім'я По-батькові
    name_pattern = r'([А-ЯІЇЄҐ][а-яіїєґ\']+(?:\s+[А-ЯІЇЄҐ][а-яіїєґ\']+){1,2})'
    
    matches = re.findall(name_pattern, clean_text)
    
    for match in matches:
        words = match.split()
        # Filter out cities and common words
        if len(words) >= 2:
            is_city = any(word.lower() in ' '.join(UKRAINIAN_CITIES) for word in words)
            if not is_city:
                return match.strip()
    
    return None


def parse_client_data(text: str) -> ClientData:
    """Parse all client data from a message text.
    
    Args:
        text: Message text from client (e.g. "Іванов Іван, 0501234567, Київ, НП 25")
    
    Returns:
        ClientData with extracted fields
    """
    return ClientData(
        full_name=extract_full_name(text),
        phone=extract_phone(text),
        city=extract_city(text),
        nova_poshta=extract_nova_poshta(text),
    )


def merge_client_data(existing: ClientData, new: ClientData) -> ClientData:
    """Merge new data into existing, keeping non-empty values."""
    return ClientData(
        full_name=new.full_name or existing.full_name,
        phone=new.phone or existing.phone,
        city=new.city or existing.city,
        nova_poshta=new.nova_poshta or existing.nova_poshta,
    )
