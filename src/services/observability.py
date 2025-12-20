"""
Observability - метрики та структуроване логування.
===================================================
Мінімальний модуль для:
- Метрики вузлів (moderation hit, tool latency, validation fails)
- Структуровані логи з тегами (state/intent/tool_result_size)
- Plan branch tracking

Використання:
    from src.services.observability import log_agent_step, track_metric, AgentMetrics

    # Log agent step
    log_agent_step(
        session_id="123",
        state="STATE_1_DISCOVERY",
        intent="DISCOVERY_OR_QUESTION",
        event="agent_response",
        tool_results_count=3,
    )

    # Track metric
    track_metric("tool_latency_ms", 150, tags={"tool": "SEARCH_BY_QUERY"})
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.conf.config import settings


logger = logging.getLogger("mirt.observability")


# =============================================================================
# METRICS STORAGE (In-memory, can be exported to Prometheus/StatsD)
# =============================================================================


@dataclass
class MetricPoint:
    """Single metric data point."""

    name: str
    value: float
    timestamp: datetime
    tags: dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """In-memory metrics collector."""

    def __init__(self, max_points: int = 10000):
        self.points: list[MetricPoint] = []
        self.max_points = max_points

    def record(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Record a metric point."""
        point = MetricPoint(
            name=name,
            value=value,
            timestamp=datetime.now(UTC),
            tags=tags or {},
        )
        self.points.append(point)

        # Prune old points if needed
        if len(self.points) > self.max_points:
            self.points = self.points[-self.max_points :]

    def get_recent(self, name: str, limit: int = 100) -> list[MetricPoint]:
        """Get recent points for a metric."""
        return [p for p in self.points[-limit:] if p.name == name]

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all metrics."""
        summary: dict[str, dict[str, Any]] = {}

        for point in self.points:
            if point.name not in summary:
                summary[point.name] = {"count": 0, "sum": 0, "min": float("inf"), "max": 0}

            s = summary[point.name]
            s["count"] += 1
            s["sum"] += point.value
            s["min"] = min(s["min"], point.value)
            s["max"] = max(s["max"], point.value)

        # Calculate averages
        for _name, s in summary.items():
            s["avg"] = s["sum"] / s["count"] if s["count"] > 0 else 0

        return summary


# Global metrics collector
_metrics = MetricsCollector()


def track_metric(name: str, value: float, tags: dict[str, str] | None = None) -> None:
    """Track a metric value."""
    _metrics.record(name, value, tags)


def get_metrics_summary() -> dict[str, Any]:
    """Get summary of all tracked metrics."""
    return _metrics.get_summary()


# =============================================================================
# TIMING CONTEXT MANAGER
# =============================================================================


@contextmanager
def timed_operation(operation_name: str, tags: dict[str, str] | None = None):
    """Context manager to time an operation and record metric."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        track_metric(f"{operation_name}_ms", elapsed_ms, tags)


# =============================================================================
# STRUCTURED LOGGING
# =============================================================================


def log_agent_step(
    session_id: str,
    state: str,
    intent: str,
    event: str,
    tool_results_count: int = 0,
    validation_errors: int = 0,
    moderation_blocked: bool = False,
    escalation_level: str = "NONE",
    latency_ms: float = 0,
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Log structured agent step with consistent tags.

    Tags:
    - session_id: conversation identifier
    - state: current FSM state
    - intent: classified intent
    - event: response event type
    - tool_results_count: number of products from tools
    - validation_errors: number of validation failures
    - moderation_blocked: whether moderation blocked the message
    - escalation_level: escalation level if any
    - latency_ms: total processing time
    """
    log_data = {
        "session_id": session_id,
        "state": state,
        "intent": intent,
        "event": event,
        "tool_results": tool_results_count,
        "validation_errors": validation_errors,
        "moderation_blocked": moderation_blocked,
        "escalation": escalation_level,
        "latency_ms": round(latency_ms, 2),
    }

    if extra:
        log_data.update(extra)

    # Format as structured log
    tags_str = " ".join(f"{k}={v}" for k, v in log_data.items())
    logger.info("agent_step %s", tags_str)

    # Track metrics
    track_metric("agent_step_latency_ms", latency_ms, {"state": state, "intent": intent})

    if tool_results_count > 0:
        track_metric("tool_results_count", tool_results_count, {"state": state})

    if validation_errors > 0:
        track_metric("validation_errors", validation_errors, {"state": state})

    if moderation_blocked:
        track_metric("moderation_blocks", 1, {"state": state})


def log_tool_execution(
    tool_name: str,
    success: bool,
    latency_ms: float,
    result_count: int = 0,
    error: str | None = None,
) -> None:
    """Log tool execution with metrics."""
    status = "success" if success else "error"

    log_data = {
        "tool": tool_name,
        "status": status,
        "latency_ms": round(latency_ms, 2),
        "results": result_count,
    }

    if error:
        log_data["error"] = error[:100]  # Truncate error message

    tags_str = " ".join(f"{k}={v}" for k, v in log_data.items())
    logger.info("tool_execution %s", tags_str)

    track_metric("tool_latency_ms", latency_ms, {"tool": tool_name, "status": status})
    track_metric("tool_results", result_count, {"tool": tool_name})


def log_moderation_result(
    session_id: str,
    allowed: bool,
    flags: list[str],
    reason: str | None = None,
) -> None:
    """Log moderation result."""
    log_data = {
        "session_id": session_id,
        "allowed": allowed,
        "flags": ",".join(flags) if flags else "none",
    }

    if reason:
        log_data["reason"] = reason[:50]

    tags_str = " ".join(f"{k}={v}" for k, v in log_data.items())
    logger.info("moderation %s", tags_str)

    if not allowed:
        track_metric("moderation_blocks", 1, {"flags": ",".join(flags)})


def log_validation_result(
    session_id: str,
    passed: bool,
    errors: list[str],
) -> None:
    """Log validation result."""
    log_data = {
        "session_id": session_id,
        "passed": passed,
        "error_count": len(errors),
    }

    if errors:
        log_data["errors"] = "; ".join(errors[:3])  # First 3 errors

    tags_str = " ".join(f"{k}={v}" for k, v in log_data.items())
    logger.info("validation %s", tags_str)

    if not passed:
        track_metric("validation_failures", len(errors))


# =============================================================================
# AGENT METRICS SUMMARY
# =============================================================================


# =============================================================================
# ASYNC TRACING SERVICE (Supabase)
# =============================================================================


class AsyncTracingService:
    """
    Background service for logging LLM traces to Supabase.

    Designed to be fire-and-forget so it doesn't block the bot.
    """

    def __init__(self):
        self._enabled = bool(getattr(settings, "ENABLE_OBSERVABILITY", True))

    @staticmethod
    def _normalize_trace_id(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return str(uuid.uuid4())
        try:
            return str(uuid.UUID(raw))
        except Exception:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))

    async def log_trace(
        self,
        session_id: str,
        trace_id: str,
        node_name: str,
        status: str,  # SUCCESS, ERROR, BLOCKED, ESCALATED
        state_name: str | None = None,
        prompt_key: str | None = None,
        prompt_version: str | None = None,
        prompt_label: str | None = None,
        input_snapshot: dict[str, Any] | None = None,
        output_snapshot: dict[str, Any] | None = None,
        error_category: str | None = None,  # SCHEMA, BUSINESS, SAFETY, SYSTEM
        error_message: str | None = None,
        latency_ms: float = 0,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost: float | None = None,
        model_name: str | None = None,
    ) -> None:
        """Log a trace record to Supabase."""
        if not self._enabled:
            return

        try:
            from src.services.supabase_client import get_supabase_client

            client = get_supabase_client()
            if not client:
                return

            payload = {
                "session_id": session_id,
                "trace_id": self._normalize_trace_id(trace_id),
                "node_name": node_name,
                "status": status,
                "state_name": state_name,
                "prompt_key": prompt_key,
                "prompt_version": prompt_version,
                "prompt_label": prompt_label,
                "input_snapshot": input_snapshot,
                "output_snapshot": output_snapshot,
                "error_category": error_category,
                "error_message": error_message,
                "latency_ms": latency_ms,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost": cost,
                "model_name": model_name,
                "created_at": datetime.now(UTC).isoformat(),
            }

            # Remove None values to let DB defaults work or avoid null issues
            payload = {k: v for k, v in payload.items() if v is not None}

            try:
                await client.table("llm_traces").insert(payload).execute()
            except Exception:
                await client.table("llm_usage").insert(payload).execute()

        except Exception as e:
            # Observability shouldn't crash the app - use debug level to avoid spam
            logger.debug(f"Failed to log trace: {e}")


# Global singleton
_tracer = AsyncTracingService()


async def log_trace(
    session_id: str,
    trace_id: str,
    node_name: str,
    status: str = "SUCCESS",
    **kwargs: Any,
) -> None:
    """Public API for logging traces."""
    await _tracer.log_trace(
        session_id=session_id, trace_id=trace_id, node_name=node_name, status=status, **kwargs
    )
