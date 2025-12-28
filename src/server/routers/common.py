"""Common utilities shared across routers."""

from __future__ import annotations

import os
from typing import Any


def get_build_info() -> dict[str, str]:
    """Extract build information from environment variables."""
    sha = (
        os.environ.get("GIT_SHA")
        or os.environ.get("COMMIT_SHA")
        or os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        or os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
        or os.environ.get("GITHUB_SHA")
        or "unknown"
    )
    build_id = (
        os.environ.get("BUILD_ID")
        or os.environ.get("RAILWAY_DEPLOYMENT_ID")
        or os.environ.get("RENDER_INSTANCE_ID")
        or os.environ.get("DYNO")
        or os.environ.get("HOSTNAME")
        or "unknown"
    )
    return {"git_sha": sha, "build_id": build_id}


def extract_manychat_message_id(payload: dict[str, Any], message: dict[str, Any]) -> str | None:
    """Extract message ID from ManyChat payload for deduplication.
    
    Prefer explicit message ids if present. If absent, we do NOT dedupe
    to avoid false positives on repeated user texts.
    """
    for key in ("id", "message_id", "messageId"):
        value = message.get(key)
        if value:
            return str(value)

    for key in ("message_id", "messageId", "event_id", "eventId", "update_id", "updateId"):
        value = payload.get(key)
        if value:
            return str(value)

    return None


def extract_inbound_token(x_header: str | None, authorization: str | None) -> str | None:
    """Extract authentication token from headers.
    
    Supports:
    - X-API-Key or X-ManyChat-Token header
    - Authorization: Bearer <token> header
    
    Returns the token value (with "Bearer " prefix stripped if present).
    """
    inbound_token = x_header
    if not inbound_token and authorization:
        auth_value = authorization.strip()
        if auth_value.lower().startswith("bearer "):
            inbound_token = auth_value[7:].strip()
        else:
            inbound_token = auth_value
    return inbound_token

