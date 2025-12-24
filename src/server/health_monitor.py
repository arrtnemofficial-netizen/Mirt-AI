"""Runtime health monitoring for critical services.

This module provides periodic health checks during runtime (not just at startup).
Tracks degradation trends and emits warnings before failures occur.

Features:
- Background task that runs every 30-60 seconds
- Checks critical services (DB, LLM, Redis)
- Tracks degradation trends (e.g., increasing latency)
- Emits warnings before failures occur
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Runtime health monitor for critical services."""
    
    def __init__(self, check_interval: float = 60.0):
        """Initialize health monitor.
        
        Args:
            check_interval: Interval between health checks in seconds (default: 60s)
        """
        self.check_interval = check_interval
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._metrics_history: dict[str, list[float]] = {}
        self._max_history = 10  # Keep last 10 measurements
    
    async def start(self) -> None:
        """Start health monitoring background task."""
        if self._running:
            logger.warning("[HEALTH_MONITOR] Already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("[HEALTH_MONITOR] Started (interval: %ds)", self.check_interval)
    
    async def stop(self) -> None:
        """Stop health monitoring background task."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[HEALTH_MONITOR] Stopped")
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_health()
            except Exception as e:
                logger.error("[HEALTH_MONITOR] Health check error: %s", e)
            
            await asyncio.sleep(self.check_interval)
    
    async def _check_health(self) -> None:
        """Perform health checks on all critical services."""
        checks_start = time.perf_counter()
        
        # Check checkpointer (pool health, latency)
        await self._check_checkpointer()
        
        # Check LLM providers (circuit breaker states)
        await self._check_llm_providers()
        
        # Check Redis (if enabled)
        await self._check_redis()
        
        checks_duration = (time.perf_counter() - checks_start) * 1000
        logger.debug("[HEALTH_MONITOR] Health checks completed in %.1fms", checks_duration)
    
    async def _check_checkpointer(self) -> None:
        """Check checkpointer health (pool utilization, latency)."""
        try:
            from src.agents.langgraph.checkpointer import get_pool_health
            
            pool_health = await get_pool_health()
            if pool_health:
                utilization = pool_health.get("utilization_percent", 0.0)
                available = pool_health.get("available", 0)
                max_size = pool_health.get("max", 0)
                
                # Track utilization trend
                self._track_metric("checkpointer_utilization", utilization)
                
                # Warn if pool is exhausted
                if pool_health.get("is_exhausted", False):
                    logger.warning(
                        "[HEALTH_MONITOR] Checkpointer pool nearly exhausted: %.1f%% (%d/%d available)",
                        utilization, available, max_size
                    )
                
                # Check for degradation trend (increasing utilization)
                trend = self._get_trend("checkpointer_utilization")
                if trend and trend > 5.0:  # Utilization increased by >5% over last checks
                    logger.warning(
                        "[HEALTH_MONITOR] Checkpointer pool utilization trending up: +%.1f%% over last checks",
                        trend
                    )
        except Exception as e:
            logger.debug("[HEALTH_MONITOR] Checkpointer health check failed: %s", e)
    
    async def _check_llm_providers(self) -> None:
        """Check LLM provider health (circuit breaker states)."""
        try:
            from src.services.infra.llm_fallback import get_llm_service
            import asyncio
            
            loop = asyncio.get_event_loop()
            llm_service = await loop.run_in_executor(None, get_llm_service)
            
            if llm_service:
                health_status = await loop.run_in_executor(
                    None, llm_service.get_health_status
                )
                
                providers = health_status.get("providers", [])
                open_circuits = [p for p in providers if p.get("circuit_state") == "open"]
                
                if open_circuits:
                    logger.warning(
                        "[HEALTH_MONITOR] %d LLM provider circuit breakers are OPEN: %s",
                        len(open_circuits),
                        [p["name"] for p in open_circuits]
                    )
                
                # Warn if all circuits are open
                if not health_status.get("any_available", False):
                    logger.error(
                        "[HEALTH_MONITOR] All LLM provider circuit breakers are OPEN - no providers available!"
                    )
        except Exception as e:
            logger.debug("[HEALTH_MONITOR] LLM provider health check failed: %s", e)
    
    async def _check_redis(self) -> None:
        """Check Redis health (if enabled)."""
        try:
            from src.conf.config import get_settings
            
            settings = get_settings()
            redis_required = (
                settings.CELERY_ENABLED or
                getattr(settings, "RATE_LIMIT_ENABLED", False)
            )
            
            if not redis_required:
                return
            
            import redis
            
            redis_url = getattr(settings, "REDIS_URL", None)
            if not redis_url:
                return
            
            # Measure latency
            latency_start = time.perf_counter()
            r = redis.from_url(redis_url, decode_responses=True)
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, r.ping),
                timeout=2.0
            )
            latency_ms = (time.perf_counter() - latency_start) * 1000
            
            # Track latency trend
            self._track_metric("redis_latency", latency_ms)
            
            # Warn if latency is high
            if latency_ms > 100:
                logger.warning(
                    "[HEALTH_MONITOR] High Redis latency: %.1fms (expected <100ms)",
                    latency_ms
                )
            
            # Check for degradation trend
            trend = self._get_trend("redis_latency")
            if trend and trend > 50.0:  # Latency increased by >50ms
                logger.warning(
                    "[HEALTH_MONITOR] Redis latency trending up: +%.1fms over last checks",
                    trend
                )
        except Exception as e:
            logger.debug("[HEALTH_MONITOR] Redis health check failed: %s", e)
    
    def _track_metric(self, metric_name: str, value: float) -> None:
        """Track metric value in history."""
        if metric_name not in self._metrics_history:
            self._metrics_history[metric_name] = []
        
        history = self._metrics_history[metric_name]
        history.append(value)
        
        # Keep only last N measurements
        if len(history) > self._max_history:
            history.pop(0)
    
    def _get_trend(self, metric_name: str) -> float | None:
        """Calculate trend for metric (difference between last and first value).
        
        Returns:
            Trend value (positive = increasing, negative = decreasing)
            None if not enough data
        """
        if metric_name not in self._metrics_history:
            return None
        
        history = self._metrics_history[metric_name]
        if len(history) < 3:  # Need at least 3 measurements
            return None
        
        # Calculate trend: difference between average of last 3 and first 3
        last_avg = sum(history[-3:]) / 3
        first_avg = sum(history[:3]) / 3
        
        return last_avg - first_avg


# Global monitor instance
_health_monitor: HealthMonitor | None = None


async def start_health_monitoring(check_interval: float = 60.0) -> None:
    """Start runtime health monitoring.
    
    Args:
        check_interval: Interval between health checks in seconds (default: 60s)
    """
    global _health_monitor
    
    if _health_monitor is None:
        _health_monitor = HealthMonitor(check_interval=check_interval)
    
    await _health_monitor.start()


async def stop_health_monitoring() -> None:
    """Stop runtime health monitoring."""
    global _health_monitor
    
    if _health_monitor:
        await _health_monitor.stop()
        _health_monitor = None

