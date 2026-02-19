"""Resilience tests for checkpointer warmup and observability fallbacks."""

from unittest.mock import AsyncMock, patch

import pytest


class _ProbeConnection:
    """Async context manager used to emulate pool.connection() probes."""

    def __init__(self, *, should_fail: bool) -> None:
        self.should_fail = should_fail

    async def __aenter__(self) -> "_ProbeConnection":
        if self.should_fail:
            raise RuntimeError("probe failed")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - API contract
        return None

    async def execute(self, *_args, **_kwargs) -> None:
        return None


class _FakePool:
    """Minimal Postgres-like pool used for deterministic warmup checks."""

    def __init__(self) -> None:
        self._pool = object()
        self.calls = 0
        self.open = AsyncMock(return_value=None)

    def connection(self) -> _ProbeConnection:
        self.calls += 1
        # First precheck probe fails, then preflight succeeds.
        return _ProbeConnection(should_fail=self.calls == 1)


class _FakeCheckpointer:
    def __init__(self) -> None:
        self.pool = _FakePool()


@pytest.mark.asyncio
async def test_warmup_fallback_metric_on_precheck_probe_failure() -> None:
    from src.agents.langgraph.checkpointer import warmup_checkpointer_pool

    fake_cp = _FakeCheckpointer()

    with (
        patch("src.agents.langgraph.checkpointer.get_checkpointer", return_value=fake_cp),
        patch("src.agents.langgraph.checkpointer.asyncio.wait_for", new=lambda awaitable, timeout: awaitable),
        patch("src.services.observability.track_metric") as track_metric_mock,
        patch("os.getenv", side_effect=lambda key, default=None: {
            "CHECKPOINTER_WARMUP": "true",
            "CHECKPOINTER_WARMUP_TIMEOUT_SECONDS": "1",
        }.get(key, default)),
    ):
        ok = await warmup_checkpointer_pool()

    assert ok is True
    assert fake_cp.pool.calls >= 2
    assert any(
        call.args[0] == "fallback_triggered"
        and call.args[2]["fallback_reason"] == "checkpointer_warmup_precheck_failed"
        for call in track_metric_mock.call_args_list
    )


def test_log_if_slow_does_not_crash_when_metrics_failing() -> None:
    from src.agents.langgraph.checkpointer import _log_if_slow

    with patch("src.services.observability.track_metric", side_effect=RuntimeError("observability down")):
        _log_if_slow(
            "test_op",
            started_at=0.0,
            config={"configurable": {"thread_id": "sess-1"}},
            payload={"messages": []},
            slow_threshold_s=0.0,
        )
