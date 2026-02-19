"""
Observability Tracer (Phase 2).
===============================
Provides a decorator @trace_node for structured logging and performance tracking.
"""

import time
import logging
import functools
from typing import Any, Callable

from src.services.observability import track_metric

logger = logging.getLogger("tracer")

def trace_node(node_name: str):
    """
    Decorator to trace LangGraph node execution.
    Logs entry, exit, latency, and errors structurally.
    """
    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        async def wrapper(state: dict[str, Any], *args, **kwargs):
            start_time = time.perf_counter()
            session_id = state.get("session_id", "unknown")
            current_state = state.get("current_state", "unknown")

            # Log Entry
            logger.info(
                "🟢 [NODE START] %s | Session: %s | State: %s",
                node_name, session_id, current_state
            )

            try:
                result = await func(state, *args, **kwargs)

                # Log Exit
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.info(
                    "🔴 [NODE END] %s | Session: %s | Latency: %.2fms",
                    node_name, session_id, latency_ms
                )

                # Track Metric
                track_metric(f"node_latency_{node_name}", latency_ms)

                return result

            except Exception as e:
                # Log Error
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.error(
                    "❌ [NODE ERROR] %s | Session: %s | Error: %s",
                    node_name, session_id, str(e), exc_info=True
                )
                track_metric(f"node_error_{node_name}", 1)
                raise e

        return wrapper
    return decorator
