"""
Metrics tracking for agent execution.

Tracks success rate, latency, tokens, and error types for observability.
"""

import logging

from src.services.observability import track_metric

logger = logging.getLogger(__name__)


def track_agent_metrics(
    agent_name: str,
    success: bool,
    latency_ms: float,
    tokens_input: int = 0,
    tokens_output: int = 0,
    error_type: str | None = None,
) -> None:
    """
    Track agent execution metrics.

    Args:
        agent_name: Name of the agent (support, vision, payment)
        success: Whether the execution was successful
        latency_ms: Execution latency in milliseconds
        tokens_input: Input tokens used
        tokens_output: Output tokens used
        error_type: Type of error if failed (optional)
    """
    # Track success/failure
    track_metric(f"agent_{agent_name}_success", 1 if success else 0)
    track_metric(f"agent_{agent_name}_latency_ms", latency_ms)

    # Track token usage
    if tokens_input > 0:
        track_metric(f"agent_{agent_name}_tokens_input", tokens_input)
    if tokens_output > 0:
        track_metric(f"agent_{agent_name}_tokens_output", tokens_output)

    # Track errors
    if error_type:
        track_metric(
            f"agent_{agent_name}_error",
            1,
            {"error_type": error_type},
        )

    # Log for debugging
    if success:
        logger.debug(
            "[METRICS] %s agent: success, latency=%.1fms, tokens_in=%d, tokens_out=%d",
            agent_name,
            latency_ms,
            tokens_input,
            tokens_output,
        )
    else:
        logger.debug(
            "[METRICS] %s agent: failed, latency=%.1fms, error=%s",
            agent_name,
            latency_ms,
            error_type or "unknown",
        )

