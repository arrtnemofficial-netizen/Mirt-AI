"""
Alerting system for critical agent errors.

Monitors agent health and sends alerts for high error rates, circuit breaker opens, etc.

PRODUCTION NOTES:
-----------------
1. In-Memory Storage: Current implementation uses in-memory dicts for error tracking.
   For production, replace with Redis using keys like:
   - agent_errors:{agent_name}:{error_type} (sorted set with timestamps)
   - agent_last_alert:{agent_name} (string with timestamp)

2. External Notifications: To integrate with Telegram/Slack:
   - Telegram: Use src/integrations/telegram/... with admin chat ID
   - Slack: Use incoming webhook URL from settings

3. Celery Beat: Add periodic task to check_agent_health for all agents every 1-5 minutes

Example Redis integration:
    import redis
    r = redis.Redis()
    r.zadd(f"agent_errors:{agent_name}:{error_type}", {str(uuid4()): now})
    r.zremrangebyscore(f"agent_errors:{agent_name}:{error_type}", 0, now - 600)
"""

import logging
import time
from collections import defaultdict

from src.services.observability import track_metric

logger = logging.getLogger(__name__)

# In-memory error tracking (for simple implementation)
# In production, this should use Redis or similar
_error_history: dict[str, list[float]] = defaultdict(list)
_last_alert_time: dict[str, float] = {}
_alert_cooldown = 300.0  # 5 minutes between alerts for same agent


def record_agent_error(agent_name: str, error_type: str) -> None:
    """
    Record an agent error for health monitoring.

    Args:
        agent_name: Name of the agent
        error_type: Type of error
    """
    now = time.time()
    error_key = f"{agent_name}:{error_type}"
    _error_history[error_key].append(now)

    # Keep only last 10 minutes of errors
    cutoff = now - 600.0
    _error_history[error_key] = [
        ts for ts in _error_history[error_key] if ts > cutoff
    ]


def get_recent_errors(agent_name: str, window_minutes: int = 5) -> int:
    """
    Get count of recent errors for an agent.

    Args:
        agent_name: Name of the agent
        window_minutes: Time window in minutes

    Returns:
        Number of errors in the window
    """
    now = time.time()
    cutoff = now - (window_minutes * 60.0)
    count = 0

    for error_key, timestamps in _error_history.items():
        if error_key.startswith(f"{agent_name}:"):
            count += sum(1 for ts in timestamps if ts > cutoff)

    return count


def check_agent_health(agent_name: str, error_threshold: int = 10) -> bool:
    """
    Check if agent is healthy based on recent metrics.

    Args:
        agent_name: Name of the agent
        error_threshold: Maximum errors in 5-minute window

    Returns:
        True if healthy, False if unhealthy
    """
    recent_errors = get_recent_errors(agent_name, window_minutes=5)

    if recent_errors > error_threshold:
        # Check cooldown
        now = time.time()
        last_alert = _last_alert_time.get(agent_name, 0)
        if now - last_alert > _alert_cooldown:
            send_alert(
                f"Agent {agent_name} has high error rate: {recent_errors} errors in 5 minutes"
            )
            _last_alert_time[agent_name] = now
        return False

    return True


def send_alert(message: str) -> None:
    """
    Send alert notification.

    Args:
        message: Alert message
    """
    logger.error("[ALERT] %s", message)
    track_metric("agent_alert", 1, {"message": message[:200]})

    # TODO: Integrate with Telegram/Slack if configured
    # For now, just log and track metric


def check_circuit_breaker_health(agent_name: str) -> None:
    """
    Check circuit breaker state and alert if open.

    Args:
        agent_name: Name of the agent
    """
    # This would check the actual circuit breaker state
    # For now, we rely on circuit breaker metrics
    track_metric(f"{agent_name}_circuit_health_check", 1)


def check_timeout_spike(agent_name: str, recent_timeouts: int, threshold: int = 5) -> None:
    """
    Check for timeout spike and alert.

    Args:
        agent_name: Name of the agent
        recent_timeouts: Number of recent timeouts
        threshold: Threshold for alerting
    """
    if recent_timeouts > threshold:
        now = time.time()
        last_alert = _last_alert_time.get(f"{agent_name}_timeout", 0)
        if now - last_alert > _alert_cooldown:
            send_alert(
                f"Agent {agent_name} has timeout spike: {recent_timeouts} timeouts"
            )
            _last_alert_time[f"{agent_name}_timeout"] = now

