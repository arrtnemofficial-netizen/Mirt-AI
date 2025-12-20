from __future__ import annotations


def normalize_image_url(value: str | None, *, max_length: int = 2000) -> str | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if not trimmed.startswith(("http://", "https://")):
        return None
    if len(trimmed) > max_length:
        return None
    return trimmed
