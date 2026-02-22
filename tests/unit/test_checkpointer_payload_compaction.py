"""Unit tests for checkpoint payload compaction and state-size hygiene."""

from src.agents.langgraph.checkpointer import _compact_payload


def test_compact_payload_trims_top_level_messages_and_content() -> None:
    payload = {
        "messages": [
            {"role": "user", "content": "a" * 50},
            {"role": "assistant", "content": "b" * 50},
            {"role": "user", "content": "c" * 50},
        ]
    }

    compact = _compact_payload(payload, max_messages=2, max_chars=10, drop_base64=False)

    assert len(compact["messages"]) == 2
    assert compact["messages"][0]["content"].endswith("...[truncated]")
    assert compact["messages"][1]["content"].endswith("...[truncated]")


def test_compact_payload_handles_nested_langgraph_state_shapes() -> None:
    nested_messages = [
        {"role": "user", "content": "x" * 30},
        {"role": "assistant", "content": "y" * 30},
        {"role": "user", "content": "z" * 30},
    ]
    payload = {
        "channel_values": {"messages": nested_messages},
        "values": {"messages": nested_messages},
        "state": {"messages": nested_messages},
    }

    compact = _compact_payload(payload, max_messages=1, max_chars=12, drop_base64=False)

    for key in ("channel_values", "values", "state"):
        assert len(compact[key]["messages"]) == 1
        assert compact[key]["messages"][0]["content"].endswith("...[truncated]")


def test_compact_payload_strips_base64_from_top_level_and_metadata() -> None:
    big_base64 = "data:image/png;base64," + ("a" * 3000)
    payload = {
        "image_url": big_base64,
        "metadata": {"image_url": big_base64},
    }

    compact = _compact_payload(payload, max_messages=0, max_chars=0, drop_base64=True)

    assert compact["image_url"] == "<base64_stripped>"
    assert compact["metadata"]["image_url"] == "<base64_stripped>"


def test_compact_payload_drops_transient_fields_and_sets_schema_version() -> None:
    payload = {
        "dialog_phase": "PAYMENT",
        "route_decision_reason": "debug",
        "debug_trace": {"step": 1},
        "current_state": "STATE_5_PAYMENT_DELIVERY",
    }

    compact = _compact_payload(payload, max_messages=0, max_chars=0, drop_base64=False)

    assert "dialog_phase" not in compact
    assert "route_decision_reason" not in compact
    assert "debug_trace" not in compact
    assert compact["checkpoint_schema_version"] == 1


def test_compact_payload_filters_metadata_by_allowlist() -> None:
    payload = {
        "metadata": {
            "session_id": "s-1",
            "current_state": "STATE_1_DISCOVERY",
            "unsafe_big_blob": "remove-me",
        }
    }

    compact = _compact_payload(payload, max_messages=0, max_chars=0, drop_base64=False)

    assert compact["metadata"]["session_id"] == "s-1"
    assert compact["metadata"]["current_state"] == "STATE_1_DISCOVERY"
    assert "unsafe_big_blob" not in compact["metadata"]
