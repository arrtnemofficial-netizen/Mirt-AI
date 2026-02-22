"""Contract tests for checkpoint payload schema/version/budget."""

from __future__ import annotations

import pytest

from src.agents.langgraph.checkpoint_contract import (
    CHECKPOINT_MAX_BYTES,
    CHECKPOINT_SCHEMA_VERSION,
    CHECKPOINT_SCHEMA_VERSION_KEY,
    ALLOWED_STATE_KEYS,
    ensure_checkpoint_schema_version,
    validate_checkpoint_payload_contract,
)


@pytest.mark.contract
def test_checkpoint_payload_has_required_schema_version_and_allowed_keys() -> None:
    payload = {
        "session_id": "cp-contract-1",
        "current_state": "STATE_4_OFFER",
        "dialog_phase": "OFFER_MADE",
        "messages": [{"role": "user", "content": "ok"}],
        "metadata": {"channel": "telegram"},
    }

    payload = ensure_checkpoint_schema_version(payload)
    violations = validate_checkpoint_payload_contract(payload)

    assert payload[CHECKPOINT_SCHEMA_VERSION_KEY] == CHECKPOINT_SCHEMA_VERSION
    assert not violations
    assert set(payload.keys()).issubset(ALLOWED_STATE_KEYS)


@pytest.mark.contract
def test_checkpoint_payload_fails_without_schema_version() -> None:
    payload = {
        "session_id": "cp-contract-2",
        "current_state": "STATE_0_INIT",
    }

    violations = validate_checkpoint_payload_contract(payload)
    assert "missing_schema_version" in violations


@pytest.mark.contract
def test_checkpoint_payload_fails_when_budget_exceeded() -> None:
    oversized = {
        "session_id": "cp-contract-3",
        "current_state": "STATE_0_INIT",
        "messages": [{"role": "user", "content": "x" * (CHECKPOINT_MAX_BYTES + 512)}],
        CHECKPOINT_SCHEMA_VERSION_KEY: CHECKPOINT_SCHEMA_VERSION,
    }

    violations = validate_checkpoint_payload_contract(oversized)
    assert any(v.startswith("payload_budget_exceeded") for v in violations)
