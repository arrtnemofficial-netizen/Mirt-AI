"""
Size Parsing Helpers.
=====================
Utilities for extracting size information from user messages and LLM responses.

This is a SAFETY NET - primary path should be structured LLM output.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# Common Ukrainian size patterns
SIZE_PATTERNS = [
    r"розмір\s*(\d{2,3}[-–]\d{2,3})",  # "розмір 146-152"
    r"раджу\s*(\d{2,3}[-–]\d{2,3})",  # "раджу 146-152"
    r"раджу\s+розмір\s+(\d{2,3})",  # "раджу розмір 98" (handles word between)
    r"раджу\s+розмір\s+(\d{2,3}[-–]\d{2,3})",  # "раджу розмір 146-152"
    r"підійде\s*(\d{2,3}[-–]\d{2,3})",  # "підійде 122-128"
    r"(\d{2,3}[-–]\d{2,3})\s*см",  # "146-152 см"
    r"розмір\s*(\d{2,3})",  # "розмір 140" or "розмір 98"
    r"раджу\s*(\d{2,3})\b",  # "раджу 98" (single number after "раджу")
]


def height_to_size(height_cm: int) -> str:
    """
    Convert height in cm to size label.
    
    ЗАЛІЗОБЕТОННЕ ПРАВИЛО: На межах (120, 131, 143, 155) НЕ переходимо в більший розмір!
    
    Лінійка відповідності:
    - 110-120 см включно → 110-116
    - 121-131 см включно → 122-128
    - 132-143 см включно → 134-140
    - 144-155 см включно → 146-152
    - 156-168 см включно → 158-164
    
    Uses the same logic as get_size_and_price_for_height but returns only size.
    
    Args:
        height_cm: Height in centimeters
        
    Returns:
        Size label (e.g., "98-104", "146-152")
    """
    if height_cm < 80:
        return "80-92"
    elif height_cm <= 92:
        return "80-92"
    elif height_cm <= 104:
        return "98-104"
    elif height_cm <= 109:
        # 105-109 см - проміжний діапазон, використовуємо найближчий менший
        return "98-104"
    elif height_cm <= 120:
        # 110-120 см включно → 110-116 (ВАЖЛИВО: 120 включно!)
        return "110-116"
    elif height_cm <= 131:
        # 121-131 см включно → 122-128 (ВАЖЛИВО: 131 включно!)
        return "122-128"
    elif height_cm <= 143:
        # 132-143 см включно → 134-140 (ВАЖЛИВО: 143 включно!)
        return "134-140"
    elif height_cm <= 155:
        # 144-155 см включно → 146-152 (ВАЖЛИВО: 155 включно!)
        return "146-152"
    elif height_cm <= 168:
        # 156-168 см включно → 158-164
        return "158-164"
    else:
        # Більше 168 см - найбільший розмір
        return "158-164"


def extract_size_from_response(messages: list[Any]) -> str | None:
    """
    Extract size from LLM response messages.
    
    Fallback when LLM forgets to include size in products[].
    Looks for patterns like "раджу 146-152", "раджу розмір 98", or "розмір 122-128".
    
    Args:
        messages: List of message objects (dict or Message objects)
        
    Returns:
        Extracted size string (e.g., "146-152") or None if not found
    """
    for msg in messages:
        content = msg.content if hasattr(msg, "content") else str(msg)
        if not content:
            continue

        for pattern in SIZE_PATTERNS:
            # Use re.IGNORECASE for proper Unicode handling
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                size = match.group(1)
                # Normalize dash
                size = size.replace("–", "-")
                logger.info(
                    "🔧 Extracted size '%s' from LLM response: %s",
                    size,
                    content[:100],
                )
                return size

    return None

