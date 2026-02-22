"""Checkpoint payload contract (schema/version/budget)."""

from __future__ import annotations

import json
from typing import Any

from src.core.state_schema import StateSchema

CHECKPOINT_SCHEMA_VERSION = "1"
CHECKPOINT_SCHEMA_VERSION_KEY = "checkpoint_schema_version"
CHECKPOINT_MAX_BYTES = 128 * 1024

ALLOWED_STATE_KEYS = frozenset(set(StateSchema.model_fields.keys()) | {CHECKPOINT_SCHEMA_VERSION_KEY})


def ensure_checkpoint_schema_version(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach schema version to payload if missing."""
    if CHECKPOINT_SCHEMA_VERSION_KEY in payload:
        return payload
    return {**payload, CHECKPOINT_SCHEMA_VERSION_KEY: CHECKPOINT_SCHEMA_VERSION}


def validate_checkpoint_payload_contract(payload: dict[str, Any]) -> list[str]:
    """Return list of contract violations for checkpoint state payload."""
    violations: list[str] = []

    if CHECKPOINT_SCHEMA_VERSION_KEY not in payload:
        violations.append("missing_schema_version")
    elif str(payload[CHECKPOINT_SCHEMA_VERSION_KEY]) != CHECKPOINT_SCHEMA_VERSION:
        violations.append("invalid_schema_version")

    unknown = sorted(set(payload.keys()) - set(ALLOWED_STATE_KEYS))
    if unknown:
        violations.append(f"unknown_keys:{','.join(unknown)}")

    size_bytes = len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    if size_bytes > CHECKPOINT_MAX_BYTES:
        violations.append(f"payload_budget_exceeded:{size_bytes}>{CHECKPOINT_MAX_BYTES}")

    return violations
