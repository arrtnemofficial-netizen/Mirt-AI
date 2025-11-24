"""Lightweight moderation and PII detection layer."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

FORBIDDEN_TERMS = {"бомба", "терорист", "суїцид", "пістолет", "вибух"}
EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_REGEX = re.compile(r"(?:\+?\d[\d\s-]{7,}\d)")


@dataclass
class ModerationResult:
    allowed: bool
    redacted_text: str
    flags: List[str]
    reason: str | None = None


def detect_pii(text: str) -> List[str]:
    flags: List[str] = []
    if EMAIL_REGEX.search(text):
        flags.append("email")
    if PHONE_REGEX.search(text):
        flags.append("phone")
    return flags


def moderate_user_message(text: str) -> ModerationResult:
    lowered = text.lower()
    flags: List[str] = []

    banned_hits = [term for term in FORBIDDEN_TERMS if term in lowered]
    if banned_hits:
        return ModerationResult(
            allowed=False,
            redacted_text="[вилучено через політику безпеки]",
            flags=["safety"] + banned_hits,
            reason="Небезпечний вміст у повідомленні користувача.",
        )

    pii_flags = detect_pii(text)
    flags.extend(pii_flags)
    redacted = text
    if pii_flags:
        redacted = EMAIL_REGEX.sub("[email]", redacted)
        redacted = PHONE_REGEX.sub("[phone]", redacted)

    return ModerationResult(allowed=True, redacted_text=redacted, flags=flags, reason=None)
