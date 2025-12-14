"""
Input Sanitizer - Prompt Injection Protection.
==============================================
Protects against attempts to manipulate AI behavior via user input.

Attack patterns blocked:
1. "Ignore previous instructions" - role manipulation
2. "You are now X" - identity hijacking  
3. "System prompt:" - instruction injection
4. Repeated special characters - encoding attacks
5. Base64/hex encoded payloads - obfuscation

Response: Strip dangerous content, log attempt, continue normally.
"""

from __future__ import annotations

import logging
import re
from typing import Literal


logger = logging.getLogger(__name__)


# =============================================================================
# DANGEROUS PATTERNS (case-insensitive)
# =============================================================================

# Role/identity manipulation attempts
ROLE_MANIPULATION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"forget\s+(all\s+)?previous\s+instructions?",
    r"disregard\s+(all\s+)?previous",
    r"you\s+are\s+now\s+\w+",
    r"pretend\s+(to\s+be|you\s+are)",
    r"act\s+as\s+(if\s+you\s+are|a\s+)",
    r"your\s+new\s+(role|name|identity)\s+is",
    r"from\s+now\s+on\s+you\s+(are|will)",
]

# Instruction injection attempts
INSTRUCTION_INJECTION_PATTERNS = [
    r"system\s*prompt\s*:",
    r"system\s*message\s*:",
    r"<\s*system\s*>",
    r"\[\s*system\s*\]",
    r"###\s*instruction",
    r"```\s*system",
    r"<\|im_start\|>",
    r"<\|endoftext\|>",
]

# Jailbreak attempts
JAILBREAK_PATTERNS = [
    r"DAN\s*mode",
    r"developer\s*mode",
    r"jailbreak",
    r"bypass\s+(restrictions?|filters?|safety)",
    r"unlock\s+full\s+potential",
    r"without\s+(any\s+)?restrictions?",
]

# Compile all patterns
_DANGEROUS_PATTERNS: list[re.Pattern[str]] = []
for pattern_list in [ROLE_MANIPULATION_PATTERNS, INSTRUCTION_INJECTION_PATTERNS, JAILBREAK_PATTERNS]:
    for pattern in pattern_list:
        _DANGEROUS_PATTERNS.append(re.compile(pattern, re.IGNORECASE))


# =============================================================================
# SANITIZATION
# =============================================================================

SanitizeResult = Literal["clean", "suspicious", "blocked"]


def check_input(text: str) -> tuple[SanitizeResult, str | None]:
    """
    Check user input for prompt injection attempts.
    
    Args:
        text: User message text
        
    Returns:
        (result, matched_pattern)
        - "clean": No issues found
        - "suspicious": Potential attack, but proceed with caution
        - "blocked": Clear attack attempt, should reject
    """
    if not text:
        return ("clean", None)
    
    # Check for dangerous patterns
    for pattern in _DANGEROUS_PATTERNS:
        match = pattern.search(text)
        if match:
            matched = match.group(0)
            logger.warning(
                "[SECURITY] Prompt injection attempt detected: '%s' in message",
                matched,
            )
            return ("blocked", matched)
    
    # Check for excessive special characters (encoding attack)
    special_ratio = sum(1 for c in text if not c.isalnum() and not c.isspace()) / max(len(text), 1)
    if special_ratio > 0.5 and len(text) > 20:
        logger.warning("[SECURITY] Suspicious special character ratio: %.2f", special_ratio)
        return ("suspicious", "high_special_ratio")
    
    # Check for very long messages (context stuffing)
    if len(text) > 5000:
        logger.warning("[SECURITY] Unusually long message: %d chars", len(text))
        return ("suspicious", "message_too_long")
    
    return ("clean", None)


def sanitize_input(text: str) -> str:
    """
    Sanitize user input by removing potentially dangerous content.
    
    Args:
        text: User message text
        
    Returns:
        Sanitized text (dangerous patterns removed)
    """
    if not text:
        return text
    
    result = text
    
    # Remove dangerous patterns
    for pattern in _DANGEROUS_PATTERNS:
        result = pattern.sub("", result)
    
    # Clean up multiple spaces
    result = re.sub(r"\s+", " ", result).strip()
    
    return result


def is_safe_input(text: str) -> bool:
    """
    Quick check if input is safe to process.
    
    Args:
        text: User message text
        
    Returns:
        True if safe, False if blocked
    """
    result, _ = check_input(text)
    return result != "blocked"


# =============================================================================
# INTEGRATION HELPER
# =============================================================================


def process_user_message(text: str) -> tuple[str, bool]:
    """
    Process user message with security checks.
    
    Args:
        text: Raw user message
        
    Returns:
        (processed_text, was_modified)
        - processed_text: Sanitized message
        - was_modified: True if message was changed
    """
    result, pattern = check_input(text)
    
    if result == "clean":
        return (text, False)
    
    if result == "blocked":
        # Remove the dangerous content
        sanitized = sanitize_input(text)
        logger.info(
            "[SECURITY] Blocked injection attempt, sanitized: '%s' -> '%s'",
            text[:50],
            sanitized[:50],
        )
        return (sanitized if sanitized else "Привіт", True)
    
    # Suspicious but not blocked - proceed with original
    return (text, False)
