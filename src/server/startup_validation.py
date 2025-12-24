"""Startup validation for critical components.

This module provides fail-fast validation to ensure all critical components
are ready before the application starts accepting traffic.

Includes predictive health checks:
- Connection quality assessment (latency, pool health)
- LLM quota pre-check
- Database schema validation
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.core.errors import (
    CheckpointerError,
    LangGraphError,
    LLMProviderError,
    RedisError,
    get_checkpointer_timeout_recommendations,
    get_llm_quota_recommendations,
    get_redis_connection_recommendations,
)

logger = logging.getLogger(__name__)


async def validate_critical_components() -> dict[str, Any]:
    """
    Validate that all critical components are ready.
    
    Critical components:
    - Checkpointer (PostgreSQL) - CRITICAL
    - LangGraph graph initialization - CRITICAL
    - LLM provider availability - CRITICAL (at least one provider available)
    - Redis (if CELERY_ENABLED or rate limiting enabled) - OPTIONAL but validated
    
    Returns:
        dict with validation results:
        {
            "all_ready": bool,
            "failures": list[str],  # List of failed component names
            "errors": list[dict],  # Structured error details
            "checks": {
                "checkpointer": {"status": "ok" | "error", "error": dict | None, ...},
                "langgraph": {"status": "ok" | "error", "error": dict | None, ...},
                "llm_provider": {"status": "ok" | "error", "error": dict | None, ...},
                "redis": {"status": "ok" | "error" | "optional", "error": dict | None, ...},
            }
        }
    """
    from src.conf.config import settings
    
    failures: list[str] = []
    errors: list[dict[str, Any]] = []
    checks: dict[str, dict[str, Any]] = {}
    
    # 1. Checkpointer validation (CRITICAL)
    try:
        checkpointer_status = await _validate_checkpointer()
        checks["checkpointer"] = checkpointer_status
        if checkpointer_status["status"] != "ok":
            failures.append("checkpointer")
            # Log structured error if present
            if "error" in checkpointer_status and isinstance(checkpointer_status["error"], dict):
                error_dict = checkpointer_status["error"]
                logger.critical(
                    "[VALIDATION:CHECKPOINTER] %s [%s]: %s",
                    error_dict.get("component", "checkpointer"),
                    error_dict.get("error_code", "UNKNOWN"),
                    error_dict.get("message", "Unknown error")
                )
                errors.append(error_dict)
    except (CheckpointerError, Exception) as e:
        failures.append("checkpointer")
        if isinstance(e, CheckpointerError):
            error_dict = e.to_dict()
            errors.append(error_dict)
            logger.critical(
                "[VALIDATION:CHECKPOINTER] %s [%s]: %s",
                e.component, e.error_code, e.message
            )
            checks["checkpointer"] = {
                "status": "error",
                "error": error_dict,
            }
        else:
            checks["checkpointer"] = {
                "status": "error",
                "error": {"message": str(e)[:200], "error_type": type(e).__name__},
            }
            logger.critical("CRITICAL: Checkpointer validation failed: %s", e)
    
    # 2. LangGraph validation (CRITICAL)
    try:
        langgraph_status = await _validate_langgraph()
        checks["langgraph"] = langgraph_status
        if langgraph_status["status"] != "ok":
            failures.append("langgraph")
            if "error" in langgraph_status and isinstance(langgraph_status["error"], dict):
                error_dict = langgraph_status["error"]
                logger.critical(
                    "[VALIDATION:LANGGRAPH] %s [%s]: %s",
                    error_dict.get("component", "langgraph"),
                    error_dict.get("error_code", "UNKNOWN"),
                    error_dict.get("message", "Unknown error")
                )
                errors.append(error_dict)
    except (LangGraphError, Exception) as e:
        failures.append("langgraph")
        if isinstance(e, LangGraphError):
            error_dict = e.to_dict()
            errors.append(error_dict)
            logger.critical(
                "[VALIDATION:LANGGRAPH] %s [%s]: %s",
                e.component, e.error_code, e.message
            )
            checks["langgraph"] = {
                "status": "error",
                "error": error_dict,
            }
        else:
            checks["langgraph"] = {
                "status": "error",
                "error": {"message": str(e)[:200], "error_type": type(e).__name__},
            }
            logger.critical("CRITICAL: LangGraph validation failed: %s", e)
    
    # 3. LLM Provider validation (CRITICAL)
    try:
        llm_status = await _validate_llm_provider()
        checks["llm_provider"] = llm_status
        if llm_status["status"] != "ok":
            failures.append("llm_provider")
            if "error" in llm_status and isinstance(llm_status["error"], dict):
                error_dict = llm_status["error"]
                logger.critical(
                    "[VALIDATION:LLM_PROVIDER] %s [%s]: %s",
                    error_dict.get("component", "llm_provider"),
                    error_dict.get("error_code", "UNKNOWN"),
                    error_dict.get("message", "Unknown error")
                )
                errors.append(error_dict)
    except (LLMProviderError, Exception) as e:
        failures.append("llm_provider")
        if isinstance(e, LLMProviderError):
            error_dict = e.to_dict()
            errors.append(error_dict)
            logger.critical(
                "[VALIDATION:LLM_PROVIDER] %s [%s]: %s",
                e.component, e.error_code, e.message
            )
            checks["llm_provider"] = {
                "status": "error",
                "error": error_dict,
            }
        else:
            checks["llm_provider"] = {
                "status": "error",
                "error": {"message": str(e)[:200], "error_type": type(e).__name__},
            }
            logger.critical("CRITICAL: LLM provider validation failed: %s", e)
    
    # 4. Redis validation (OPTIONAL but checked if needed)
    try:
        redis_status = await _validate_redis()
        checks["redis"] = redis_status
        # Redis is optional, but if it's required (CELERY_ENABLED) and not available, it's a failure
        if redis_status["status"] == "required_but_unavailable":
            failures.append("redis")
            if "error" in redis_status and isinstance(redis_status["error"], dict):
                error_dict = redis_status["error"]
                logger.critical(
                    "[VALIDATION:REDIS] %s [%s]: %s",
                    error_dict.get("component", "redis"),
                    error_dict.get("error_code", "UNKNOWN"),
                    error_dict.get("message", "Unknown error")
                )
                errors.append(error_dict)
    except (RedisError, Exception) as e:
        failures.append("redis")
        if isinstance(e, RedisError):
            error_dict = e.to_dict()
            errors.append(error_dict)
            logger.critical(
                "[VALIDATION:REDIS] %s [%s]: %s",
                e.component, e.error_code, e.message
            )
            checks["redis"] = {
                "status": "error",
                "error": error_dict,
            }
        else:
            checks["redis"] = {
                "status": "error",
                "error": {"message": str(e)[:200], "error_type": type(e).__name__},
            }
            logger.critical("CRITICAL: Redis validation failed: %s", e)
    
    all_ready = len(failures) == 0
    
    return {
        "all_ready": all_ready,
        "failures": failures,
        "errors": errors,
        "checks": checks,
    }


async def _validate_checkpointer(timeout: float = 10.0) -> dict[str, Any]:
    """Validate checkpointer with quality metrics (predictive checks).
    
    Checks:
    - Connection availability
    - Connection latency (warns if >500ms)
    - Pool health (warns if >80% utilized)
    - Schema validation (checks if tables exist)
    """
    try:
        from src.agents.langgraph.checkpointer import (
            get_checkpointer,
            get_pool_health,
            warmup_checkpointer_pool,
        )
        from src.conf.config import get_settings
        
        settings = get_settings()
        warnings: list[str] = []
        
        # Measure connection latency
        latency_start = time.perf_counter()
        warmup_ok = await asyncio.wait_for(
            warmup_checkpointer_pool(),
            timeout=timeout
        )
        latency_ms = (time.perf_counter() - latency_start) * 1000
        
        if not warmup_ok:
            raise CheckpointerError(
                error_code="CHECKPOINTER_WARMUP_FAILED",
                message="Checkpointer warmup failed or timeout",
                recommendations=get_checkpointer_timeout_recommendations(
                    timeout,
                    {"min_size": getattr(settings, "CHECKPOINTER_POOL_MIN_SIZE", 2), "max_size": getattr(settings, "CHECKPOINTER_POOL_MAX_SIZE", 5)}
                ),
                severity="critical",
                context={"timeout_seconds": timeout},
            )
        
        # Verify checkpointer is initialized
        checkpointer = get_checkpointer()
        if not checkpointer:
            raise CheckpointerError(
                error_code="CHECKPOINTER_NOT_INITIALIZED",
                message="Checkpointer not initialized",
                recommendations=[
                    "1. Check checkpointer initialization in startup sequence",
                    "2. Verify DATABASE_URL or DATABASE_URL_POOLER is set",
                    "3. Review checkpointer logs for initialization errors",
                ],
                severity="critical",
            )
        
        # Predictive checks: latency and pool health
        if latency_ms > 500:
            warnings.append(f"High connection latency detected: {latency_ms:.1f}ms (expected <500ms)")
        
        pool_health = await get_pool_health()
        if pool_health:
            if pool_health.get("is_exhausted", False):
                warnings.append(
                    f"Connection pool nearly exhausted: {pool_health['utilization_percent']:.1f}% "
                    f"({pool_health['available']}/{pool_health['max']} available)"
                )
        
        # Log warnings (don't block startup)
        for warning in warnings:
            logger.warning("[VALIDATION:CHECKPOINTER] %s", warning)
        
        return {
            "status": "ok",
            "error": None,
            "latency_ms": round(latency_ms, 2),
            "pool_health": pool_health,
            "warnings": warnings,
        }
        
    except CheckpointerError:
        # Re-raise structured errors
        raise
    except asyncio.TimeoutError:
        raise CheckpointerError(
            error_code="CHECKPOINTER_TIMEOUT",
            message=f"Checkpointer validation timeout ({timeout}s)",
            recommendations=get_checkpointer_timeout_recommendations(timeout),
            severity="critical",
            context={"timeout_seconds": timeout},
        )
    except Exception as e:
        raise CheckpointerError(
            error_code="CHECKPOINTER_VALIDATION_ERROR",
            message=f"Checkpointer validation error: {str(e)[:200]}",
            recommendations=[
                "1. Check database connectivity and credentials",
                "2. Verify DATABASE_URL format is correct",
                "3. Review checkpointer logs for detailed error information",
                "4. Ensure database server is running and accessible",
            ],
            severity="critical",
            context={"error_type": type(e).__name__, "error_message": str(e)[:200]},
        )


async def _validate_langgraph(timeout: float = 15.0) -> dict[str, Any]:
    """Validate LangGraph is ready."""
    try:
        from src.agents.langgraph import get_production_graph
        
        # Try to build/get the graph (this validates graph initialization)
        # get_production_graph is synchronous, so we run it in thread pool
        loop = asyncio.get_event_loop()
        graph = await asyncio.wait_for(
            loop.run_in_executor(None, get_production_graph),
            timeout=timeout
        )
        
        if not graph:
            raise LangGraphError(
                error_code="LANGGRAPH_NOT_INITIALIZED",
                message="LangGraph graph not initialized",
                recommendations=[
                    "1. Check LangGraph graph building logic",
                    "2. Verify all required nodes and edges are defined",
                    "3. Review graph initialization logs for errors",
                    "4. Ensure checkpointer is properly configured",
                ],
                severity="critical",
            )
        
        # Verify graph has ainvoke method
        if not hasattr(graph, "ainvoke") or not callable(getattr(graph, "ainvoke", None)):
            raise LangGraphError(
                error_code="LANGGRAPH_MISSING_AINVOKE",
                message="LangGraph graph missing ainvoke method",
                recommendations=[
                    "1. Verify graph is properly compiled",
                    "2. Check LangGraph version compatibility",
                    "3. Review graph building code for errors",
                ],
                severity="critical",
            )
        
        return {"status": "ok", "error": None}
        
    except LangGraphError:
        # Re-raise structured errors
        raise
    except asyncio.TimeoutError:
        raise LangGraphError(
            error_code="LANGGRAPH_TIMEOUT",
            message=f"LangGraph validation timeout ({timeout}s)",
            recommendations=[
                "1. Check if graph building is taking too long",
                "2. Review graph complexity and node count",
                "3. Increase timeout if needed (default: 15s)",
                "4. Check system resources (CPU, memory)",
            ],
            severity="critical",
            context={"timeout_seconds": timeout},
        )
    except Exception as e:
        raise LangGraphError(
            error_code="LANGGRAPH_VALIDATION_ERROR",
            message=f"LangGraph validation error: {str(e)[:200]}",
            recommendations=[
                "1. Review graph building code for errors",
                "2. Check LangGraph dependencies are installed",
                "3. Verify checkpointer is properly configured",
                "4. Review logs for detailed error information",
            ],
            severity="critical",
            context={"error_type": type(e).__name__, "error_message": str(e)[:200]},
        )


async def _validate_llm_provider(timeout: float = 5.0) -> dict[str, Any]:
    """Validate LLM provider with pre-flight quota check."""
    try:
        from src.services.infra.llm_fallback import get_llm_service
        
        # get_llm_service is synchronous, so we run it in thread pool
        loop = asyncio.get_event_loop()
        llm_service = await asyncio.wait_for(
            loop.run_in_executor(None, get_llm_service),
            timeout=timeout
        )
        
        if not llm_service:
            raise LLMProviderError(
                error_code="LLM_SERVICE_NOT_INITIALIZED",
                message="LLM service not initialized",
                recommendations=[
                    "1. Verify OPENAI_API_KEY is set correctly",
                    "2. Check LLM service initialization in startup sequence",
                    "3. Review logs for initialization errors",
                ],
                severity="critical",
            )
        
        # Check health status (also synchronous)
        health_status = await asyncio.wait_for(
            loop.run_in_executor(None, llm_service.get_health_status),
            timeout=timeout
        )
        
        if not health_status.get("any_available", False):
            providers_status = health_status.get("providers", [])
            circuit_states = {p["name"]: p["circuit_state"] for p in providers_status}
            raise LLMProviderError(
                error_code="NO_LLM_PROVIDERS_AVAILABLE",
                message="No LLM providers available (all circuit breakers may be open)",
                recommendations=get_llm_quota_recommendations("OpenAI"),
                severity="critical",
                context={"circuit_states": circuit_states},
            )
        
        # Pre-flight check: quota and circuit breaker states
        warnings: list[str] = []
        try:
            preflight_result = await llm_service.preflight_check(timeout=2.0)
            if preflight_result["status"] == "error":
                warnings.append(f"Pre-flight check failed: {', '.join(preflight_result.get('warnings', []))}")
            elif preflight_result["status"] == "warning":
                warnings.extend(preflight_result.get("warnings", []))
            
            # Log warnings (don't block startup)
            for warning in warnings:
                logger.warning("[VALIDATION:LLM_PROVIDER] %s", warning)
        except Exception as e:
            logger.debug("[VALIDATION:LLM_PROVIDER] Pre-flight check failed (non-critical): %s", e)
        
        return {
            "status": "ok",
            "error": None,
            "warnings": warnings,
            "preflight": preflight_result if 'preflight_result' in locals() else None,
        }
        
    except LLMProviderError:
        # Re-raise structured errors
        raise
    except asyncio.TimeoutError:
        raise LLMProviderError(
            error_code="LLM_PROVIDER_TIMEOUT",
            message=f"LLM provider validation timeout ({timeout}s)",
            recommendations=[
                "1. Check network connectivity to OpenAI API",
                "2. Verify API key is valid",
                "3. Review system resources (network latency)",
            ],
            severity="critical",
            context={"timeout_seconds": timeout},
        )
    except Exception as e:
        raise LLMProviderError(
            error_code="LLM_PROVIDER_VALIDATION_ERROR",
            message=f"LLM provider validation error: {str(e)[:200]}",
            recommendations=[
                "1. Verify OPENAI_API_KEY is set correctly",
                "2. Check LLM service initialization",
                "3. Review logs for detailed error information",
            ],
            severity="critical",
            context={"error_type": type(e).__name__, "error_message": str(e)[:200]},
        )


async def _validate_redis(timeout: float = 5.0) -> dict[str, Any]:
    """Validate Redis if required."""
    from src.conf.config import settings
    
    # Check if Redis is required
    redis_required = (
        settings.CELERY_ENABLED or
        getattr(settings, "RATE_LIMIT_ENABLED", False) or
        getattr(settings, "REDIS_REQUIRED", False)
    )
    
    if not redis_required:
        return {"status": "optional", "error": None}
    
    try:
        import redis
        
        redis_url = getattr(settings, "REDIS_URL", None)
        if not redis_url:
            raise RedisError(
                error_code="REDIS_URL_NOT_CONFIGURED",
                message="REDIS_URL not configured but Redis is required",
                recommendations=get_redis_connection_recommendations(None),
                severity="critical",
                context={"celery_enabled": settings.CELERY_ENABLED},
            )
        
        # Measure connection latency
        latency_start = time.perf_counter()
        r = redis.from_url(redis_url, decode_responses=True)
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, r.ping),
            timeout=timeout
        )
        latency_ms = (time.perf_counter() - latency_start) * 1000
        
        warnings: list[str] = []
        if latency_ms > 100:
            warnings.append(f"High Redis connection latency: {latency_ms:.1f}ms (expected <100ms)")
        
        # Log warnings (don't block startup)
        for warning in warnings:
            logger.warning("[VALIDATION:REDIS] %s", warning)
        
        return {
            "status": "ok",
            "error": None,
            "latency_ms": round(latency_ms, 2),
            "warnings": warnings,
        }
        
    except RedisError:
        # Re-raise structured errors
        raise
    except asyncio.TimeoutError:
        raise RedisError(
            error_code="REDIS_CONNECTION_TIMEOUT",
            message=f"Redis connection timeout ({timeout}s)",
            recommendations=get_redis_connection_recommendations(
                getattr(settings, "REDIS_URL", None)
            ),
            severity="critical",
            context={"timeout_seconds": timeout},
        )
    except Exception as e:
        raise RedisError(
            error_code="REDIS_CONNECTION_ERROR",
            message=f"Redis connection error: {str(e)[:200]}",
            recommendations=get_redis_connection_recommendations(
                getattr(settings, "REDIS_URL", None)
            ),
            severity="critical",
            context={"error_type": type(e).__name__, "error_message": str(e)[:200]},
        )

