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

from src.core.constants import ModerationFlag
from src.services.core.moderation_config import get_forbidden_terms, get_substitution_map


FORBIDDEN_TERMS: set[str] = get_forbidden_terms()
SUBSTITUTION_MAP = get_substitution_map()

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
    r"\b[\u0410-\u042F\u0406\u0407\u0404\u0490]{2}\s?\d{6}\b",
    re.IGNORECASE,
)

_INJECTION_PATTERNS_RAW: list[str] = [
    # Override / ignore instructions
    "ignore all previous",
    "ignore previous instructions",
    "ignore earlier instructions",
    "disregard previous",
    "forget previous",
    "forget everything",
    "override instructions",
    "bypass rules",
    "break the rules",
    "do anything now",
    "jailbreak",
    # Slavic variants (common)
    "игнорируй предыдущие",
    "игнорируй все предыдущие",
    "забудь предыдущие",
    "выйди из роли",
    "ігноруй попередні",
    "забудь попередні",
    "вийди з ролі",
    # Prompt / system disclosure
    "system prompt",
    "developer message",
    "hidden instructions",
    "reveal instructions",
    "show me the prompt",
    "print the prompt",
    "prompt injection",
    # Role / identity manipulation
    "new role",
    "act as",
    "you are now",
    "from now on",
    "pretend to be",
    # Structured role attempts (common in chat APIs)
    "role system",
    "role developer",
    "role assistant",
    "content system",
    "begin system",
    "end system",
    # Tool / function call coercion
    "call the tool",
    "use tool",
    "function call",
    "execute code",
]

# Pre-normalize to catch obfuscation efficiently.
try:
    _INJECTION_PATTERNS_NORM = [normalize_text(p) for p in _INJECTION_PATTERNS_RAW if p]
except Exception:
    _INJECTION_PATTERNS_NORM = []


@dataclass
class ModerationResult:
    """Result of content moderation check."""

    allowed: bool
    redacted_text: str
    flags: list[str]
    reason: str | None = None


def normalize_text(text: str) -> str:
    """Normalize text for pattern matching.

    - Converts to lowercase
    - Normalizes Unicode (NFD decomposition)
    - Applies substitution map for leetspeak/look-alikes
    - Removes diacritics
    - Collapses repeated characters
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Lowercase
    result = text.lower()

    # Unicode normalization
    result = unicodedata.normalize("NFD", result)

    # Remove diacritics (combining characters)
    result = "".join(char for char in result if unicodedata.category(char) != "Mn")

    # Apply substitutions
    normalized = []
    for char in result:
        normalized.append(SUBSTITUTION_MAP.get(char, char))
    result = "".join(normalized)

    # Collapse repeated characters (e.g., "booomba" -> "bomba")
    try:
        result = re.sub(r"(.)\1{2,}", r"\1", result)
    except re.error as e:
        logger.warning("Regex error in normalize_text (collapse repeated): %s (pos=%s)", str(e), getattr(e, "pos", "unknown"))
        # Continue with original result

    # Remove non-alphanumeric except spaces
    try:
        result = re.sub(r"[^\w\s]", "", result)
    except re.error as e:
        logger.warning("Regex error in normalize_text (remove non-alphanumeric): %s (pos=%s)", str(e), getattr(e, "pos", "unknown"))
        # Continue with previous result

    return result


def detect_forbidden_terms(text: str) -> list[str]:
    """Detect forbidden terms with normalization for evasion attempts."""
    normalized = normalize_text(text)
    found = []

    for term in FORBIDDEN_TERMS:
        # Also normalize the term for comparison
        normalized_term = normalize_text(term)
        if normalized_term in normalized:
            found.append(term)

    return found


def detect_pii(text: str) -> list[str]:
    """Detect personally identifiable information in text."""
    flags: list[str] = []

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


def detect_prompt_injection(text: str) -> bool:
    """Detect simple prompt injection patterns."""
    # Use normalized text to catch obfuscation (unicode variants, leetspeak, punctuation).
    normalized = normalize_text(text)
    if not normalized:
        return False
    return any(pat in normalized for pat in _INJECTION_PATTERNS_NORM)


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

    flags: list[str] = []

    # Check for prompt injection FIRST
    from src.core.prompt_registry import get_snippet_by_header

    def _get_snippet_text(header: str, default: str) -> str:
        s = get_snippet_by_header(header)
        return "\n".join(s) if s else default

    if detect_prompt_injection(text):
        return ModerationResult(
            allowed=False,
            redacted_text="[blocked]",
            flags=[ModerationFlag.SAFETY, "prompt_injection"],
            reason=_get_snippet_text("MODERATION_INJECTION_REASON", "Instruction manipulation attempt detected."),
        )

    # Check for forbidden terms
    banned_hits = detect_forbidden_terms(text)
    if banned_hits:
        return ModerationResult(
            allowed=False,
            redacted_text=_get_snippet_text("MODERATION_REDACTED_TEXT", "[removed due to safety policy]"),
            flags=[ModerationFlag.SAFETY, *banned_hits],
            reason=_get_snippet_text("MODERATION_FORBIDDEN_REASON", "Dangerous content in user message."),
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
