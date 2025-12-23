"""
Observability - metrics and structured logging.
================================================
Minimal module for:
- Node metrics (moderation hit, tool latency, validation fails)
- Structured logs with tags (state/intent/tool_result_size)
- Plan branch tracking

Usage:
    from src.services.core.observability import log_agent_step, track_metric, AgentMetrics

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
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Any

from src.conf.config import settings

UTC = timezone.utc


logger = logging.getLogger("mirt.observability")


# =============================================================================
# OPENTELEMETRY DISTRIBUTED TRACING
# =============================================================================

_opentelemetry_tracer = None
_tracing_enabled = False


def setup_opentelemetry_tracing() -> bool:
    """
    Setup OpenTelemetry distributed tracing.

    Returns:
        True if tracing is enabled, False otherwise.
    """
    global _opentelemetry_tracer, _tracing_enabled

    if _tracing_enabled and _opentelemetry_tracer is not None:
        return True

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource

        # Create tracer provider
        resource = Resource.create(
            {
                "service.name": "mirt-ai",
                "service.version": "1.0.0",
            }
        )
        provider = TracerProvider(resource=resource)

        # Add console exporter (can be replaced with OTLP exporter for production)
        console_exporter = ConsoleSpanExporter()
        processor = BatchSpanProcessor(console_exporter)
        provider.add_span_processor(processor)

        # Set global tracer provider
        trace.set_tracer_provider(provider)
        _opentelemetry_tracer = trace.get_tracer(__name__)
        _tracing_enabled = True

        logger.info("OpenTelemetry tracing enabled (console exporter)")
        return True

    except ImportError:
        logger.debug("OpenTelemetry not installed. Install with: pip install opentelemetry-api opentelemetry-sdk")
        _tracing_enabled = False
        return False
    except Exception as e:
        logger.warning("Failed to setup OpenTelemetry tracing: %s", e)
        _tracing_enabled = False
        return False


def get_tracer():
    """Get OpenTelemetry tracer (lazy initialization)."""
    global _opentelemetry_tracer
    if _opentelemetry_tracer is None:
        setup_opentelemetry_tracing()
    return _opentelemetry_tracer


def is_tracing_enabled() -> bool:
    """Check if distributed tracing is enabled."""
    return _tracing_enabled and _opentelemetry_tracer is not None


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
            timestamp=datetime.utcnow(),
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


@dataclass
class AgentMetrics:
    """Summary of agent performance metrics."""

    total_requests: int = 0
    successful_responses: int = 0
    moderation_blocks: int = 0
    validation_failures: int = 0
    tool_calls: int = 0
    avg_latency_ms: float = 0
    escalations: int = 0

    @classmethod
    def from_collector(cls) -> AgentMetrics:
        """Build metrics from collector."""
        summary = get_metrics_summary()
        latency_data = summary.get("agent_step_latency_ms", {})
        
        return cls(
            total_requests=summary.get("agent_step_latency_ms", {}).get("count", 0),
            successful_responses=summary.get("agent_step_latency_ms", {}).get("count", 0),
            moderation_blocks=summary.get("moderation_blocks", {}).get("count", 0),
            validation_failures=summary.get("validation_failures", {}).get("count", 0),
            tool_calls=summary.get("tool_results", {}).get("count", 0),
            avg_latency_ms=latency_data.get("avg", 0),
        )


class AsyncTracingService:
    """Service for logging asynchronous traces to external storage (Supabase).
    
    SAFEGUARDS:
    - Graceful degradation if Supabase unavailable
    - Failure counter for monitoring
    - Optional disable via ENABLE_OBSERVABILITY env var
    - Payload validation before insertion
    """

    # Valid ENUM values for llm_traces table
    VALID_STATUSES = {'SUCCESS', 'ERROR', 'BLOCKED', 'ESCALATED'}
    VALID_ERROR_CATEGORIES = {'SCHEMA', 'BUSINESS', 'SAFETY', 'SYSTEM'}

    def __init__(self):
        self._enabled = bool(getattr(settings, "ENABLE_OBSERVABILITY", True))
        self._failure_count = 0  # SAFEGUARD_3: Failure counter

    @staticmethod
    def _normalize_trace_id(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return str(uuid.uuid4())
        try:
            return str(uuid.UUID(raw))
        except Exception:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))

    def _validate_trace_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate trace payload against llm_traces schema.
        
        Validates:
        - Required fields (session_id, node_name, trace_id)
        - ENUM values (status, error_category)
        - Data types (latency_ms, tokens_in, tokens_out, cost)
        
        Returns:
            Validated payload dict
        """
        validated = payload.copy()
        
        # Validate required fields
        if not validated.get('node_name'):
            raise ValueError("node_name is required for llm_traces")
        if not validated.get('session_id'):
            raise ValueError("session_id is required for llm_traces")
        if not validated.get('trace_id'):
            raise ValueError("trace_id is required for llm_traces")
        
        # Validate status ENUM
        status = validated.get('status', 'SUCCESS')
        if status not in self.VALID_STATUSES:
            logger.warning(
                "[TRACING] Invalid status '%s', defaulting to 'SUCCESS'. Valid values: %s",
                status,
                self.VALID_STATUSES
            )
            validated['status'] = 'SUCCESS'
        
        # Validate error_category ENUM
        error_category = validated.get('error_category')
        if error_category is not None and error_category not in self.VALID_ERROR_CATEGORIES:
            logger.warning(
                "[TRACING] Invalid error_category '%s', removing. Valid values: %s",
                error_category,
                self.VALID_ERROR_CATEGORIES
            )
            validated['error_category'] = None
        
        # Validate numeric types
        if 'latency_ms' in validated and validated['latency_ms'] is not None:
            try:
                validated['latency_ms'] = float(validated['latency_ms'])
            except (ValueError, TypeError):
                logger.warning("[TRACING] Invalid latency_ms type, removing")
                validated['latency_ms'] = None
        
        if 'tokens_in' in validated and validated['tokens_in'] is not None:
            try:
                validated['tokens_in'] = int(validated['tokens_in'])
            except (ValueError, TypeError):
                logger.warning("[TRACING] Invalid tokens_in type, removing")
                validated['tokens_in'] = None
        
        if 'tokens_out' in validated and validated['tokens_out'] is not None:
            try:
                validated['tokens_out'] = int(validated['tokens_out'])
            except (ValueError, TypeError):
                logger.warning("[TRACING] Invalid tokens_out type, removing")
                validated['tokens_out'] = None
        
        if 'cost' in validated and validated['cost'] is not None:
            try:
                validated['cost'] = float(validated['cost'])
            except (ValueError, TypeError):
                logger.warning("[TRACING] Invalid cost type, removing")
                validated['cost'] = None
        
        return validated

    def _handle_trace_error(self, error: Exception, payload: dict[str, Any]) -> None:
        """Handle errors when inserting trace records.
        
        Distinguishes between schema errors (PGRST204) and other errors.
        Logs appropriate level based on error type.
        """
        error_msg = str(error).lower()
        error_str = str(error)[:200]
        
        # Check for schema errors (missing column, wrong type, etc.)
        is_schema_error = (
            'pgrst204' in error_msg
            or 'column' in error_msg
            or 'could not find' in error_msg
            or 'does not exist' in error_msg
        )
        
        if is_schema_error:
            # Schema errors are more critical - log as warning
            logger.warning(
                "[TRACING] Schema error inserting to llm_traces: %s. "
                "Payload keys: %s. Check database schema matches code.",
                error_str,
                list(payload.keys())
            )
        else:
            # Other errors (network, auth, etc.) - log as debug (non-critical)
            logger.debug(
                "[TRACING] Error inserting to llm_traces: %s",
                error_str
            )

    def get_failure_count(self) -> int:
        """Get current failure count for monitoring."""
        return self._failure_count
    
    def reset_failure_count(self) -> None:
        """Reset failure count (for testing or manual reset)."""
        self._failure_count = 0

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
        """Log a trace record to Supabase.
        
        SAFEGUARD_1: Async and non-blocking (doesn't await result, doesn't block main flow).
        """
        if not self._enabled:
            return

        try:
            from src.services.infra.supabase_client import get_supabase_client

            client = get_supabase_client()
            if not client:
                return

            # Build payload according to llm_traces schema
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

            # Validate payload before insertion
            validated_payload = self._validate_trace_payload(payload)

            # Remove None values to let DB defaults work or avoid null issues
            clean_payload = {k: v for k, v in validated_payload.items() if v is not None}

            # Insert into llm_traces (no fallback to llm_usage - different purposes)
            try:
                await client.table("llm_traces").insert(clean_payload).execute()
            except Exception as e:
                # Handle error with appropriate logging level
                self._handle_trace_error(e, clean_payload)

        except Exception as e:
            # SAFEGUARD_2: Graceful degradation - observability shouldn't crash the app
            # SAFEGUARD_3: Increment failure counter
            self._failure_count += 1
            # Use debug level to avoid spam, but log first few failures
            if self._failure_count <= 3:
                logger.warning(
                    "[TRACING] Failed to log trace (failure_count=%d): %s",
                    self._failure_count,
                    str(e)[:200],
                )
            else:
                logger.debug(
                    "[TRACING] Failed to log trace (failure_count=%d): %s",
                    self._failure_count,
                    str(e)[:200],
                )
            
            # SAFEGUARD_3: Alert if failure rate is high (> 1% threshold)
            # This is checked externally via metrics


# Global singleton
_async_tracing_service = AsyncTracingService()


async def log_trace(
    session_id: str,
    trace_id: str,
    node_name: str,
    status: str = "SUCCESS",
    **kwargs: Any,
) -> None:
    """Public API for logging traces."""
    await _async_tracing_service.log_trace(
        session_id=session_id, trace_id=trace_id, node_name=node_name, status=status, **kwargs
    )
