from __future__ import annotations

from src.agents.langgraph.checkpointer import _compact_payload


def test_compact_payload_trims_nested_messages_and_base64() -> None:
    payload = {
        "channel_values": {
            "messages": [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
                {"role": "user", "content": "three"},
            ],
            "image_url": "data:image/png;base64,AAAA" * 500,
        }
    }

    compact = _compact_payload(
        payload,
        max_messages=2,
        max_chars=5,
        drop_base64=True,
    )

    messages = compact["channel_values"]["messages"]
    assert len(messages) == 2
    assert messages[0]["content"] == "two"
    assert messages[1]["content"].startswith("three")
    assert compact["channel_values"]["image_url"] == "<base64_stripped>"
