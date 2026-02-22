from __future__ import annotations

import copy

from src.agents.langgraph.checkpointer import _checkpoint_stats, _compact_payload
from src.services.observability import get_metrics_summary, track_metric


def _mk_msg(i: int) -> dict[str, str]:
    return {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i} " + ("x" * 120)}


def test_checkpoint_payload_growth_is_bounded_with_rolling_summary() -> None:
    payload: dict[str, object] = {"messages": []}
    sizes: list[int] = []

    for i in range(1, 260):
        payload = copy.deepcopy(payload)
        messages = list(payload.get("messages", []))
        messages.append(_mk_msg(i))
        payload["messages"] = messages

        payload = _compact_payload(
            payload,
            max_messages=200,
            max_chars=200,
            drop_base64=True,
            rolling_summary_enabled=True,
            rolling_summary_last_messages=12,
            rolling_summary_max_chars=1200,
        )
        size_b, _ = _checkpoint_stats(payload)
        assert size_b is not None
        sizes.append(size_b)

    tail = sizes[-50:]
    assert max(tail) - min(tail) < 2000, "payload size should plateau and stop linear growth"


def test_compaction_metrics_are_reported() -> None:
    before = {
        "messages": [
            {"role": "user", "content": "a" * 500},
            {"role": "assistant", "content": "b" * 500},
            {"role": "user", "content": "c" * 500},
            {"role": "assistant", "content": "d" * 500},
        ]
    }
    after = _compact_payload(
        before,
        max_messages=2,
        max_chars=100,
        drop_base64=True,
        rolling_summary_enabled=True,
        rolling_summary_last_messages=1,
        rolling_summary_max_chars=400,
    )
    before_bytes, _ = _checkpoint_stats(before)
    after_bytes, _ = _checkpoint_stats(after)
    assert before_bytes and after_bytes is not None

    ratio = max(0.0, min(1.0, 1.0 - (after_bytes / before_bytes)))
    track_metric("checkpoint_payload_bytes", float(after_bytes), {"operation": "test"})
    track_metric("checkpoint_compaction_ratio", ratio, {"operation": "test"})

    summary = get_metrics_summary()
    assert "checkpoint_payload_bytes" in summary
    assert "checkpoint_compaction_ratio" in summary
