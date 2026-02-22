from __future__ import annotations

from src.agents.langgraph.checkpointer import (
    CHECKPOINT_SCHEMA_VERSION,
    JsonCheckpointSerializer,
    _migrate_legacy_checkpoint_payload,
    _normalize_checkpoint_payload,
    normalize_checkpoint_state,
)


def test_normalize_checkpoint_state_applies_whitelist_and_drops_derived_fields() -> None:
    raw_state = {
        "session_id": "s1",
        "current_state": "STATE_2_VISION",
        "dialog_phase": "VISION",
        "selected_products": [{"sku": "A"}],
        "metadata": {
            "session_id": "s1",
            "channel": "instagram",
            "language": "uk",
            "unknown_meta": "drop-me",
        },
        "messages": [{"role": "user", "content": "hello"}],
        "temp_context": {"foo": "bar"},
        "validation_errors": ["x"],
        "unknown_field": "must_drop",
    }

    normalized = normalize_checkpoint_state(raw_state, max_messages=10)

    assert normalized["session_id"] == "s1"
    assert normalized["current_state"] == "STATE_2_VISION"
    assert "dialog_phase" not in normalized
    assert "unknown_field" not in normalized
    assert "temp_context" not in normalized
    assert "validation_errors" not in normalized
    assert normalized["metadata"] == {
        "session_id": "s1",
        "channel": "instagram",
        "language": "uk",
    }


def test_normalize_checkpoint_state_trims_messages_with_summary_kept() -> None:
    messages = [
        {"type": "user", "content": "m0"},
        {"type": "assistant", "content": "m1"},
        {"type": "summary", "content": "previous summary"},
        {"type": "assistant", "content": "m2"},
        {"type": "user", "content": "m3"},
        {"type": "assistant", "content": "m4"},
    ]

    normalized = normalize_checkpoint_state(
        {
            "session_id": "s2",
            "current_state": "STATE_1_DISCOVERY",
            "messages": messages,
        },
        max_messages=2,
    )

    trimmed = normalized["messages"]
    assert len(trimmed) == 3
    assert trimmed[0]["type"] == "summary"
    assert [m["content"] for m in trimmed[1:]] == ["m3", "m4"]


def test_normalize_checkpoint_payload_adds_schema_version_and_normalizes_sections() -> None:
    payload = {
        "id": "cp-1",
        "channel_values": {
            "session_id": "s3",
            "current_state": "STATE_1_DISCOVERY",
            "dialog_phase": "DISCOVERY",
            "messages": [{"type": "user", "content": "hello"}],
            "unknown": "drop",
        },
        "writes": {
            "session_id": "s3",
            "current_state": "STATE_1_DISCOVERY",
            "messages": [{"type": "user", "content": "hello"}],
            "temp_context": {"k": "v"},
        },
    }

    normalized = _normalize_checkpoint_payload(payload, max_messages=5)

    assert normalized["checkpoint_schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert "dialog_phase" not in normalized["channel_values"]
    assert "unknown" not in normalized["channel_values"]
    assert "temp_context" not in normalized["writes"]


def test_serializer_loads_legacy_payload_with_backward_compatibility() -> None:
    serializer = JsonCheckpointSerializer()

    legacy_payload = {
        "id": "legacy-cp",
        "channel_values": {
            "current_state": "STATE_1_DISCOVERY",
            "dialog_phase": "DISCOVERY",
            "messages": [{"content": "x"}],
        },
    }
    data = serializer.dumps(legacy_payload)

    restored = serializer.loads(data)

    assert restored["checkpoint_schema_version"] == 1
    assert "dialog_phase" not in restored["channel_values"]


def test_explicit_legacy_migration_keeps_new_schema_untouched() -> None:
    payload = {
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "channel_values": {"current_state": "STATE_0_INIT", "dialog_phase": "INIT"},
    }

    migrated = _migrate_legacy_checkpoint_payload(payload)

    assert migrated is payload
