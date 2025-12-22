"""Input sanitization for user messages.

Provides defense against:
- SQL injection (via parameterized queries - this module handles text sanitization)
- XSS attacks
- Prompt injection attempts
- Control characters and excessive length
"""

from __future__ import annotations

import html
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Maximum message length (characters)
MAX_MESSAGE_LENGTH = 10000

# Control characters to remove (except newlines, tabs, carriage returns)
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]")

# Common prompt injection patterns
# NOTE: Patterns without inline flags - using re.IGNORECASE flag on compilation
# to avoid "global flags not at the start" error when joining with |
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"forget\s+(all\s+)?previous\s+instructions?",
    r"you\s+are\s+now\s+(a\s+)?(different|new)",
    r"system\s*:",
    r"assistant\s*:",
    r"user\s*:",
    r"role\s*:",
    r"act\s+as\s+if",
    r"pretend\s+to\s+be",
    r"disregard\s+(all\s+)?previous",
    r"override\s+(all\s+)?previous",
    r"new\s+instructions?\s*:",
    r"new\s+task\s*:",
    r"new\s+system\s+message",
    r"new\s+prompt",
    r"bypass\s+(all\s+)?(safety|security|filters?)",
    r"jailbreak",
    r"hack",
    r"exploit",
    r"vulnerability",
    r"secret\s+(key|token|password)",
    r"api\s+key",
    r"admin\s+(access|privileges?)",
    r"root\s+access",
    r"sudo",
    r"execute\s+(command|code)",
    r"run\s+(command|code)",
    r"<script",
    r"javascript\s*:",
    r"onerror\s*=",
    r"onload\s*=",
    r"eval\s*\(",
    r"exec\s*\(",
]

# Compile patterns once with IGNORECASE flag instead of inline (?i) flags
# This avoids "global flags not at the start" error when patterns are joined with |
try:
    PROMPT_INJECTION_REGEX = re.compile("|".join(PROMPT_INJECTION_PATTERNS), re.IGNORECASE)
except re.error as e:
    logger.error(
        "Failed to compile PROMPT_INJECTION_REGEX: %s (pos=%s). Using empty pattern as fallback.",
        str(e),
        getattr(e, "pos", "unknown"),
    )
    # Fallback: regex that matches nothing
    PROMPT_INJECTION_REGEX = re.compile(r"(?!.)", re.IGNORECASE)


def sanitize_text(text: str) -> tuple[str, bool]:
    """Sanitize user input text.

    Args:
        text: Raw user input text

    Returns:
        Tuple of (sanitized_text, was_modified)
    """
    if not text or not isinstance(text, str):
        return "", False

    original_text = text
    was_modified = False

    # 1. Remove control characters (except newlines, tabs, carriage returns)
    sanitized = CONTROL_CHAR_PATTERN.sub("", text)
    if sanitized != text:
        was_modified = True
        logger.debug("Removed control characters from input")

    # 2. Normalize whitespace (collapse multiple spaces, preserve newlines)
    try:
        sanitized = re.sub(r"[ \t]+", " ", sanitized)
        sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)  # Max 2 consecutive newlines
    except re.error as e:
        logger.warning(
            "Regex error in sanitize_text (whitespace normalization): %s (pos=%s)",
            str(e),
            getattr(e, "pos", "unknown"),
        )
        # Continue with current sanitized value
    if sanitized != text:
        was_modified = True

    # 3. Truncate if too long
    if len(sanitized) > MAX_MESSAGE_LENGTH:
        sanitized = sanitized[:MAX_MESSAGE_LENGTH]
        was_modified = True
        logger.warning("Message truncated to %d characters", MAX_MESSAGE_LENGTH)

    # 4. Escape HTML entities to prevent XSS
    # Note: We escape but don't mark as modified since this is standard practice
    sanitized = html.escape(sanitized, quote=False)

    # 5. Detect prompt injection patterns (log but don't modify - let moderation handle)
    try:
        if PROMPT_INJECTION_REGEX.search(sanitized):
            logger.warning(
                "Potential prompt injection detected in message (length=%d)",
                len(sanitized),
            )
            # Don't modify the text - let the moderation layer handle it
            # This allows the system to track and respond appropriately
    except re.error as e:
        logger.warning(
            "Regex error in sanitize_text (prompt injection detection): %s (pos=%s)",
            str(e),
            getattr(e, "pos", "unknown"),
        )
        # Continue without injection detection for this message

    # 6. Remove null bytes
    if "\x00" in sanitized:
        sanitized = sanitized.replace("\x00", "")
        was_modified = True

    # 7. Strip leading/trailing whitespace
    sanitized_stripped = sanitized.strip()
    if sanitized_stripped != sanitized:
        was_modified = True
        sanitized = sanitized_stripped

    return sanitized, was_modified


def process_user_message(text: str) -> tuple[str, bool]:
    """Process and sanitize user message.

    This is the main entry point for sanitizing user input.
    Used in conversation handlers and webhook endpoints.

    Args:
        text: Raw user message text

    Returns:
        Tuple of (sanitized_text, was_sanitized)
    """
    if not text:
        return "", False

    sanitized, was_modified = sanitize_text(text)

    return sanitized, was_modified
