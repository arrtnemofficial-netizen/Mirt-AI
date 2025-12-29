"""
Tracing for agent calls.

Creates spans for agent execution with tags and logs for observability.
"""

import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

try:
    import logfire
    LOGFIRE_AVAILABLE = True
except ImportError:
    LOGFIRE_AVAILABLE = False

from src.services.observability import track_metric

logger = logging.getLogger(__name__)

T = TypeVar("T")


def trace_agent_call(agent_name: str):
    """
    Tracing decorator for agent calls.

    Creates spans with tags and logs for observability.

    Args:
        agent_name: Name of the agent (support, vision, payment)

    Usage:
        @trace_agent_call(agent_name="support")
        async def run_support(...):
            ...
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.perf_counter()
            span = None

            # Extract session_id from deps if available
            session_id = "unknown"
            if args and hasattr(args[1], "session_id"):  # deps is typically second arg
                session_id = args[1].session_id or "unknown"

            # Create span if Logfire is available
            if LOGFIRE_AVAILABLE:
                try:
                    span = logfire.span(
                        msg_template=f"agent.{agent_name}",
                        attributes={
                            "agent_name": agent_name,
                            "session_id": session_id,
                        },
                    )
                    span.__enter__()
                except Exception as e:
                    logger.warning("Failed to create Logfire span: %s", e)
                    span = None

            try:
                # Log start
                logger.debug(
                    "[TRACE] %s agent call started: session_id=%s",
                    agent_name,
                    session_id,
                )

                # Execute function
                result = await func(*args, **kwargs)

                # NOTE: Token extraction happens in the agent runner itself (run_support, run_vision, run_payment)
                # via metrics.py track_agent_metrics(). Tracing decorator focuses on span timing and session info.
                # This avoids duplication and ensures single source of truth for token metrics.

                # Extract metadata from result if available (SupportResponse/VisionResponse/PaymentResponse)
                if hasattr(result, "metadata"):
                    if hasattr(result.metadata, "current_state"):
                        # Add state to span
                        if span and LOGFIRE_AVAILABLE:
                            try:
                                span.set_attribute("current_state", result.metadata.current_state)
                            except Exception:
                                pass
                    if hasattr(result.metadata, "intent"):
                        if span and LOGFIRE_AVAILABLE:
                            try:
                                span.set_attribute("intent", result.metadata.intent)
                            except Exception:
                                pass
                
                # Extract event type if available
                if hasattr(result, "event"):
                    if span and LOGFIRE_AVAILABLE:
                        try:
                            span.set_attribute("event", result.event)
                        except Exception:
                            pass
                
                # Extract confidence for vision responses
                if hasattr(result, "confidence"):
                    if span and LOGFIRE_AVAILABLE:
                        try:
                            span.set_attribute("confidence", result.confidence)
                        except Exception:
                            pass

                # Log success
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                logger.debug(
                    "[TRACE] %s agent call succeeded: session_id=%s, latency=%.1fms",
                    agent_name,
                    session_id,
                    latency_ms,
                )

                # Add final span attributes
                if span and LOGFIRE_AVAILABLE:
                    try:
                        span.set_attribute("latency_ms", latency_ms)
                        span.set_attribute("success", True)
                    except Exception:
                        pass

                return result

            except Exception as e:
                # Log error
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                error_type = type(e).__name__
                logger.error(
                    "[TRACE] %s agent call failed: session_id=%s, latency=%.1fms, error=%s",
                    agent_name,
                    session_id,
                    latency_ms,
                    error_type,
                )

                # Add error to span
                if span and LOGFIRE_AVAILABLE:
                    try:
                        span.set_attribute("success", False)
                        span.set_attribute("error_type", error_type)
                        span.set_attribute("error_message", str(e)[:200])
                        span.record_exception(e)
                    except Exception:
                        pass

                raise

            finally:
                # Close span
                if span and LOGFIRE_AVAILABLE:
                    try:
                        span.__exit__(None, None, None)
                    except Exception:
                        pass

        return wrapper

    return decorator

