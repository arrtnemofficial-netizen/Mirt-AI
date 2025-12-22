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
    import logging
    import json
    import time
    logger = logging.getLogger(__name__)
    
    # #region agent log
    try:
        with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B", "location": "client_data_parser.py:extract_phone:entry", "message": "extract_phone called", "data": {"text_len": len(text) if text else 0, "text_preview": text[:50] if text else None}, "timestamp": int(time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # #endregion
    
    text_lower = text.lower()

    for idx, pattern in enumerate(PHONE_PATTERNS):
        # #region agent log
        try:
            with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "client_data_parser.py:extract_phone:pattern_check", "message": "Checking pattern", "data": {"pattern_idx": idx, "pattern": pattern, "pattern_len": len(pattern), "pattern_pos47": pattern[47:52] if len(pattern) > 47 else None}, "timestamp": int(time.time() * 1000)}) + "\n")
        except Exception:
            pass
        # #endregion
        
        try:
            # Check if pattern already has inline flags (e.g., (?i) or (?i:...))
            # If pattern has inline flags, don't add re.IGNORECASE to avoid conflict
            flags = 0
            try:
                inline_flags_check = re.search(r"\(\?[iI]", pattern)
            except re.error as check_err:
                # #region agent log
                try:
                    with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "E", "location": "client_data_parser.py:extract_phone:flags_check_error", "message": "Error checking inline flags", "data": {"pattern_idx": idx, "pattern": pattern, "error": str(check_err)}, "timestamp": int(time.time() * 1000)}) + "\n")
                except Exception:
                    pass
                # #endregion
                inline_flags_check = None
            
            # #region agent log
            try:
                with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "D", "location": "client_data_parser.py:extract_phone:flags_check", "message": "Inline flags check", "data": {"pattern_idx": idx, "has_inline_flags": bool(inline_flags_check), "will_use_ignorecase": not bool(inline_flags_check)}, "timestamp": int(time.time() * 1000)}) + "\n")
            except Exception:
                pass
            # #endregion
            
            if not inline_flags_check:
                flags = re.IGNORECASE
            compiled = re.compile(pattern, flags)
            match = compiled.search(text_lower)
            if match:
                return normalize_phone(match.group(0))
        except re.error as e:
            # #region agent log
            try:
                with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "client_data_parser.py:extract_phone:regex_error", "message": "Regex error in extract_phone", "data": {"pattern_idx": idx, "pattern": pattern, "error": str(e), "error_type": type(e).__name__}, "timestamp": int(time.time() * 1000)}) + "\n")
            except Exception:
                pass
            # #endregion
            
            # Log problematic pattern for debugging
            logger.warning(
                "Invalid regex pattern in extract_phone (skipping): %s. Error: %s",
                pattern[:100],
                str(e)
            )
            continue

    return None


def extract_nova_poshta(text: str) -> str | None:
    """Extract Nova Poshta branch number from text."""
    import logging
    import json
    import time
    logger = logging.getLogger(__name__)
    
    # #region agent log
    try:
        with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "client_data_parser.py:extract_nova_poshta:entry", "message": "extract_nova_poshta called", "data": {"text_len": len(text) if text else 0, "text_preview": text[:50] if text else None}, "timestamp": int(time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # #endregion
    
    text_lower = text.lower()

    for idx, pattern in enumerate(NP_PATTERNS):
        # #region agent log
        try:
            with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "client_data_parser.py:extract_nova_poshta:pattern_check", "message": "Checking pattern", "data": {"pattern_idx": idx, "pattern": pattern, "pattern_len": len(pattern), "pattern_pos47": pattern[47:52] if len(pattern) > 47 else None}, "timestamp": int(time.time() * 1000)}) + "\n")
        except Exception:
            pass
        # #endregion
        
        try:
            # Check if pattern already has inline flags (e.g., (?i) or (?i:...))
            # If pattern has inline flags, don't add re.IGNORECASE to avoid conflict
            flags = 0
            try:
                inline_flags_check = re.search(r"\(\?[iI]", pattern)
            except re.error as check_err:
                # #region agent log
                try:
                    with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "E", "location": "client_data_parser.py:extract_nova_poshta:flags_check_error", "message": "Error checking inline flags", "data": {"pattern_idx": idx, "pattern": pattern, "error": str(check_err)}, "timestamp": int(time.time() * 1000)}) + "\n")
                except Exception:
                    pass
                # #endregion
                inline_flags_check = None
            
            if not inline_flags_check:
                flags = re.IGNORECASE
            compiled = re.compile(pattern, flags)
            match = compiled.search(text_lower)
            if match:
                return match.group(1)
        except re.error as e:
            # #region agent log
            try:
                with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "client_data_parser.py:extract_nova_poshta:regex_error", "message": "Regex error in extract_nova_poshta", "data": {"pattern_idx": idx, "pattern": pattern, "error": str(e), "error_type": type(e).__name__}, "timestamp": int(time.time() * 1000)}) + "\n")
            except Exception:
                pass
            # #endregion
            
            # Log problematic pattern for debugging
            logger.warning(
                "Invalid regex pattern in extract_nova_poshta (skipping): %s. Error: %s",
                pattern[:100],
                str(e)
            )
            continue

    if any(word in text_lower for word in NP_KEYWORDS):
        numbers = re.findall(r"\b(\d{1,4})\b", text)
        for num in numbers:
            if 1 <= int(num) <= 9999:
                return num

    return None


def extract_city(text: str) -> str | None:
    """Extract city name from text."""
    import logging
    import json
    import time
    logger = logging.getLogger(__name__)
    
    # #region agent log
    try:
        with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "client_data_parser.py:extract_city:entry", "message": "extract_city called", "data": {"text_len": len(text) if text else 0, "text_preview": text[:50] if text else None}, "timestamp": int(time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # #endregion
    
    text_lower = text.lower()

    for city in UKRAINIAN_CITIES:
        if city in text_lower:
            return city.title()

    for idx, pattern in enumerate(CITY_PATTERNS):
        # #region agent log
        try:
            with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "client_data_parser.py:extract_city:pattern_check", "message": "Checking pattern", "data": {"pattern_idx": idx, "pattern": pattern, "pattern_len": len(pattern), "pattern_pos47": pattern[47:52] if len(pattern) > 47 else None}, "timestamp": int(time.time() * 1000)}) + "\n")
        except Exception:
            pass
        # #endregion
        
        try:
            # Check if pattern already has inline flags (e.g., (?i) or (?i:...))
            # If pattern has inline flags, don't add re.IGNORECASE to avoid conflict
            flags = 0
            try:
                inline_flags_check = re.search(r"\(\?[iI]", pattern)
            except re.error as check_err:
                # #region agent log
                try:
                    with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "E", "location": "client_data_parser.py:extract_city:flags_check_error", "message": "Error checking inline flags", "data": {"pattern_idx": idx, "pattern": pattern, "error": str(check_err)}, "timestamp": int(time.time() * 1000)}) + "\n")
                except Exception:
                    pass
                # #endregion
                inline_flags_check = None
            
            if not inline_flags_check:
                flags = re.IGNORECASE
            compiled = re.compile(pattern, flags)
            match = compiled.search(text)
            if match:
                return match.group(1).strip().title()
        except re.error as e:
            # #region agent log
            try:
                with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "client_data_parser.py:extract_city:regex_error", "message": "Regex error in extract_city", "data": {"pattern_idx": idx, "pattern": pattern, "error": str(e), "error_type": type(e).__name__}, "timestamp": int(time.time() * 1000)}) + "\n")
            except Exception:
                pass
            # #endregion
            
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
    import logging
    import json
    import time
    logger = logging.getLogger(__name__)
    
    # #region agent log
    try:
        with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C", "location": "client_data_parser.py:extract_full_name:entry", "message": "extract_full_name called", "data": {"text_len": len(text) if text else 0, "text_preview": text[:100] if text else None}, "timestamp": int(time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # #endregion
    
    clean_text = text
    for idx, pattern in enumerate(PHONE_PATTERNS):
        # #region agent log
        try:
            with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "client_data_parser.py:extract_full_name:pattern_sub", "message": "Substituting pattern", "data": {"pattern_idx": idx, "pattern": pattern, "pattern_len": len(pattern), "pattern_pos47": pattern[47:52] if len(pattern) > 47 else None}, "timestamp": int(time.time() * 1000)}) + "\n")
        except Exception:
            pass
        # #endregion
        
        try:
            # Check if pattern already has inline flags (e.g., (?i) or (?i:...))
            # If pattern has inline flags, don't add re.IGNORECASE to avoid conflict
            flags = 0
            try:
                inline_flags_check = re.search(r"\(\?[iI]", pattern)
            except re.error as check_err:
                # #region agent log
                try:
                    with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "E", "location": "client_data_parser.py:extract_full_name:flags_check_error", "message": "Error checking inline flags", "data": {"pattern_idx": idx, "pattern": pattern, "error": str(check_err)}, "timestamp": int(time.time() * 1000)}) + "\n")
                except Exception:
                    pass
                # #endregion
                inline_flags_check = None
            
            if not inline_flags_check:
                flags = re.IGNORECASE
            compiled = re.compile(pattern, flags)
            clean_text = compiled.sub("", clean_text)
        except re.error as e:
            # #region agent log
            try:
                with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "client_data_parser.py:extract_full_name:regex_error", "message": "Regex error in extract_full_name pattern sub", "data": {"pattern_idx": idx, "pattern": pattern, "error": str(e), "error_type": type(e).__name__, "error_msg": str(e)}, "timestamp": int(time.time() * 1000)}) + "\n")
            except Exception:
                pass
            # #endregion
            
            # Log problematic pattern for debugging
            logger.warning(
                "Invalid regex pattern in extract_full_name (skipping): %s. Error: %s",
                pattern[:100],
                str(e)
            )
            continue

    # #region agent log
    try:
        with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C", "location": "client_data_parser.py:extract_full_name:name_pattern_check", "message": "Checking NAME_PATTERN", "data": {"name_pattern": NAME_PATTERN, "name_pattern_len": len(NAME_PATTERN) if NAME_PATTERN else 0, "name_pattern_pos47": NAME_PATTERN[47:52] if NAME_PATTERN and len(NAME_PATTERN) > 47 else None, "clean_text_len": len(clean_text)}, "timestamp": int(time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # #endregion
    
    try:
        matches = re.findall(NAME_PATTERN, clean_text)
    except re.error as e:
        # #region agent log
        try:
            with open(r"c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C", "location": "client_data_parser.py:extract_full_name:name_pattern_error", "message": "Regex error in NAME_PATTERN", "data": {"name_pattern": NAME_PATTERN, "error": str(e), "error_type": type(e).__name__, "error_msg": str(e)}, "timestamp": int(time.time() * 1000)}) + "\n")
        except Exception:
            pass
        # #endregion
        
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
    return ClientData(
        full_name=extract_full_name(text),
        phone=extract_phone(text),
        city=extract_city(text),
        nova_poshta=extract_nova_poshta(text),
    )
