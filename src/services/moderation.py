"""Lightweight moderation and PII detection layer.

This module provides text normalization and pattern matching for:
- Safety violations (dangerous terms)
- PII detection and redaction (emails, phones, card numbers)
- Leetspeak and evasion detection
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Set

from src.core.constants import ModerationFlag

# Base forbidden terms
FORBIDDEN_TERMS: Set[str] = {
    "бомба", "терорист", "суїцид", "пістолет", "вибух",
    "вбити", "смерть", "зброя", "наркотик", "героїн",
}

# Leetspeak and Cyrillic substitution map for normalization
SUBSTITUTION_MAP = {
    # Cyrillic look-alikes
    "а": "a", "е": "e", "і": "i", "о": "o", "р": "p",
    "с": "c", "у": "y", "х": "x", "А": "a", "В": "b",
    "Е": "e", "К": "k", "М": "m", "Н": "h", "О": "o",
    "Р": "p", "С": "c", "Т": "t", "У": "y", "Х": "x",
    # Common leetspeak
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "7": "t", "8": "b", "@": "a", "$": "s", "!": "i",
}

# Regex patterns
EMAIL_REGEX = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    re.IGNORECASE,
)
PHONE_REGEX = re.compile(
    r"(?:\+?\d[\d\s\-().]{7,}\d)",
)
# Credit card pattern (basic)
CARD_REGEX = re.compile(
    r"\b(?:\d{4}[\s-]?){3}\d{4}\b",
)
# Ukrainian passport series
PASSPORT_REGEX = re.compile(
    r"\b[А-ЯІЇЄҐ]{2}\s?\d{6}\b",
    re.IGNORECASE,
)


@dataclass
class ModerationResult:
    """Result of content moderation check."""

    allowed: bool
    redacted_text: str
    flags: List[str]
    reason: str | None = None


def normalize_text(text: str) -> str:
    """Normalize text for pattern matching.

    - Converts to lowercase
    - Normalizes Unicode (NFD decomposition)
    - Applies substitution map for leetspeak/look-alikes
    - Removes diacritics
    - Collapses repeated characters
    """
    # Lowercase
    result = text.lower()

    # Unicode normalization
    result = unicodedata.normalize("NFD", result)

    # Remove diacritics (combining characters)
    result = "".join(
        char for char in result
        if unicodedata.category(char) != "Mn"
    )

    # Apply substitutions
    normalized = []
    for char in result:
        normalized.append(SUBSTITUTION_MAP.get(char, char))
    result = "".join(normalized)

    # Collapse repeated characters (e.g., "booomba" -> "bomba")
    result = re.sub(r"(.)\1{2,}", r"\1", result)

    # Remove non-alphanumeric except spaces
    result = re.sub(r"[^\w\s]", "", result)

    return result


def detect_forbidden_terms(text: str) -> List[str]:
    """Detect forbidden terms with normalization for evasion attempts."""
    normalized = normalize_text(text)
    found = []

    for term in FORBIDDEN_TERMS:
        # Also normalize the term for comparison
        normalized_term = normalize_text(term)
        if normalized_term in normalized:
            found.append(term)

    return found


def detect_pii(text: str) -> List[str]:
    """Detect personally identifiable information in text."""
    flags: List[str] = []

    if EMAIL_REGEX.search(text):
        flags.append(ModerationFlag.EMAIL)

    if PHONE_REGEX.search(text):
        flags.append(ModerationFlag.PHONE)

    if CARD_REGEX.search(text):
        flags.append(ModerationFlag.PII)

    if PASSPORT_REGEX.search(text):
        flags.append(ModerationFlag.PII)

    return flags


def redact_pii(text: str) -> str:
    """Redact PII from text, replacing with placeholders."""
    redacted = text
    redacted = EMAIL_REGEX.sub("[email]", redacted)
    redacted = PHONE_REGEX.sub("[phone]", redacted)
    redacted = CARD_REGEX.sub("[card]", redacted)
    redacted = PASSPORT_REGEX.sub("[document]", redacted)
    return redacted


def moderate_user_message(text: str) -> ModerationResult:
    """Perform full moderation check on user message.

    Checks for:
    1. Forbidden/dangerous terms (with normalization)
    2. PII (emails, phones, cards, documents)

    Returns:
        ModerationResult with allowed status, redacted text, and flags
    """
    if not text or not text.strip():
        return ModerationResult(
            allowed=True,
            redacted_text=text,
            flags=[],
            reason=None,
        )

    flags: List[str] = []

    # Check for forbidden terms
    banned_hits = detect_forbidden_terms(text)
    if banned_hits:
        return ModerationResult(
            allowed=False,
            redacted_text="[вилучено через політику безпеки]",
            flags=[ModerationFlag.SAFETY] + banned_hits,
            reason="Небезпечний вміст у повідомленні користувача.",
        )

    # Detect and redact PII
    pii_flags = detect_pii(text)
    flags.extend(pii_flags)

    redacted = text
    if pii_flags:
        redacted = redact_pii(text)

    return ModerationResult(
        allowed=True,
        redacted_text=redacted,
        flags=flags,
        reason=None,
    )
