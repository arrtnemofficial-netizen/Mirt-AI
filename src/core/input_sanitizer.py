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
PROMPT_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?previous\s+instructions?",
    r"(?i)forget\s+(all\s+)?previous\s+instructions?",
    r"(?i)you\s+are\s+now\s+(a\s+)?(different|new)",
    r"(?i)system\s*:",
    r"(?i)assistant\s*:",
    r"(?i)user\s*:",
    r"(?i)role\s*:",
    r"(?i)act\s+as\s+if",
    r"(?i)pretend\s+to\s+be",
    r"(?i)disregard\s+(all\s+)?previous",
    r"(?i)override\s+(all\s+)?previous",
    r"(?i)new\s+instructions?\s*:",
    r"(?i)new\s+task\s*:",
    r"(?i)new\s+system\s+message",
    r"(?i)new\s+prompt",
    r"(?i)bypass\s+(all\s+)?(safety|security|filters?)",
    r"(?i)jailbreak",
    r"(?i)hack",
    r"(?i)exploit",
    r"(?i)vulnerability",
    r"(?i)secret\s+(key|token|password)",
    r"(?i)api\s+key",
    r"(?i)admin\s+(access|privileges?)",
    r"(?i)root\s+access",
    r"(?i)sudo",
    r"(?i)execute\s+(command|code)",
    r"(?i)run\s+(command|code)",
    r"(?i)<script",
    r"(?i)javascript\s*:",
    r"(?i)onerror\s*=",
    r"(?i)onload\s*=",
    r"(?i)eval\s*\(",
    r"(?i)exec\s*\(",
]

# Compile patterns once
PROMPT_INJECTION_REGEX = re.compile("|".join(PROMPT_INJECTION_PATTERNS))


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
    sanitized = re.sub(r"[ \t]+", " ", sanitized)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)  # Max 2 consecutive newlines
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
    if PROMPT_INJECTION_REGEX.search(sanitized):
        logger.warning(
            "Potential prompt injection detected in message (length=%d)",
            len(sanitized),
        )
        # Don't modify the text - let the moderation layer handle it
        # This allows the system to track and respond appropriately

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
