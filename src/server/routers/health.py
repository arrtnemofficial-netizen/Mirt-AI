"""Health check router.

Extracted from main.py to reduce God Object pattern.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from src.conf.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _get_build_info() -> dict[str, str]:
    sha = (
        os.environ.get("GIT_SHA")
        or os.environ.get("COMMIT_SHA")
        or os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        or os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
        or os.environ.get("GITHUB_SHA")
        or "unknown"
    )
    build_id = (
        os.environ.get("BUILD_ID")
        or os.environ.get("RAILWAY_DEPLOYMENT_ID")
        or os.environ.get("RENDER_INSTANCE_ID")
        or os.environ.get("DYNO")
        or os.environ.get("HOSTNAME")
        or "unknown"
    )
    return {"git_sha": sha, "build_id": build_id}


@router.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint with dependency status."""
    from src.services.infra.supabase_client import get_supabase_client

    status = "ok"
    checks: dict[str, Any] = {}

    # \u041f\u0435\u0440\u0435\u0432\u0456\u0440\u043a\u0430 Supabase
    try:
        client = get_supabase_client()
        if client:
            client.table(settings.SUPABASE_TABLE).select("session_id").limit(1).execute()
            checks["supabase"] = "ok"
        else:
            checks["supabase"] = "disabled"
    except Exception as e:
        checks["supabase"] = f"error: {type(e).__name__}"
        status = "degraded"
        logger.warning("Health check: Supabase unavailable: %s", e)

    # \u041f\u0435\u0440\u0435\u0432\u0456\u0440\u043a\u0430 Redis (\u044f\u043a\u0449\u043e Celery \u0443\u0432\u0456\u043c\u043a\u043d\u0435\u043d\u043e)
    if settings.CELERY_ENABLED:
        try:
            import redis

            r = redis.from_url(settings.REDIS_URL)
            r.ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {type(e).__name__}"
            status = "degraded"
            logger.warning("Health check: Redis unavailable: %s", e)

        # Celery worker status
        try:
            from src.workers.celery_app import celery_app

            inspect = celery_app.control.inspect()
            active = inspect.active()
            if active:
                worker_count = len(active)
                checks["celery_workers"] = {"status": "ok", "count": worker_count}
            else:
                checks["celery_workers"] = "no_workers"
                status = "degraded"
        except Exception as e:
            checks["celery_workers"] = f"error: {type(e).__name__}"
    else:
        checks["celery"] = "disabled"

    # LLM Provider health (circuit breaker status)
    try:
        from src.services.infra.llm_fallback import get_llm_service

        llm_service = get_llm_service()
        llm_health = llm_service.get_health_status()
        checks["llm"] = {
            "any_available": llm_health["any_available"],
            "providers": [
                {"name": p["name"], "status": p["circuit_state"], "available": p["available"]}
                for p in llm_health["providers"]
            ],
        }
        if not llm_health["any_available"]:
            status = "degraded"
    except Exception as e:
        checks["llm"] = f"error: {type(e).__name__}"
        status = "degraded"

    # External API circuit breakers
    try:
        from src.core.circuit_breaker import get_circuit_breaker

        manychat_cb = get_circuit_breaker("manychat_api")
        sitniks_cb = get_circuit_breaker("sitniks_api")

        checks["external_apis"] = {
            "manychat": manychat_cb.get_status(),
            "sitniks": sitniks_cb.get_status(),
        }

        # Check if any critical API is down
        if not manychat_cb.can_execute() and settings.MANYCHAT_API_KEY.get_secret_value():
            status = "degraded"
            logger.warning("Health check: ManyChat API circuit breaker is OPEN")
        if not sitniks_cb.can_execute() and settings.snitkix_enabled:
            status = "degraded"
            logger.warning("Health check: Sitniks API circuit breaker is OPEN")
    except Exception as e:
        checks["external_apis"] = f"error: {type(e).__name__}"
        logger.warning("Health check: Failed to check external API circuit breakers: %s", e)

    # LangGraph health check
    try:
        from src.agents import get_active_graph

        graph = get_active_graph()
        if graph:
            checks["langgraph"] = {"status": "ok", "graph_compiled": True}
        else:
            checks["langgraph"] = {"status": "error", "error": "Graph not initialized"}
            status = "degraded"
    except Exception as e:
        checks["langgraph"] = {"status": "error", "error": str(e)[:100]}
        status = "degraded"
        logger.warning("Health check: LangGraph unavailable: %s", e)

    # PydanticAI agents health check
    try:
        from src.agents.pydantic.main_agent import get_main_agent, get_offer_agent
        from src.agents.pydantic.vision_agent import get_vision_agent
        from src.agents.pydantic.payment_agent import get_payment_agent

        main_agent = get_main_agent()
        offer_agent = get_offer_agent()
        vision_agent = get_vision_agent()
        payment_agent = get_payment_agent()

        checks["pydantic_ai_agents"] = {
            "status": "ok",
            "main_agent": "available",
            "offer_agent": "available",
            "vision_agent": "available",
            "payment_agent": "available",
        }
    except Exception as e:
        checks["pydantic_ai_agents"] = {"status": "error", "error": str(e)[:100]}
        status = "degraded"
        logger.warning("Health check: PydanticAI agents unavailable: %s", e)

    # Checkpointer health check
    try:
        from src.agents.langgraph.checkpointer import get_checkpointer, is_persistent

        checkpointer = get_checkpointer()
        if checkpointer:
            checks["checkpointer"] = {
                "status": "ok",
                "persistent": is_persistent(),
            }
        else:
            checks["checkpointer"] = {"status": "error", "error": "Checkpointer not initialized"}
            status = "degraded"
    except Exception as e:
        checks["checkpointer"] = {"status": "error", "error": str(e)[:100]}
        status = "degraded"
        logger.warning("Health check: Checkpointer unavailable: %s", e)

    # PydanticAI circuit breakers status
    try:
        from src.core.circuit_breaker import get_circuit_breaker

        main_cb = get_circuit_breaker("pydantic_ai_main_agent")
        offer_cb = get_circuit_breaker("pydantic_ai_offer_agent")
        vision_cb = get_circuit_breaker("pydantic_ai_vision_agent")
        payment_cb = get_circuit_breaker("pydantic_ai_payment_agent")

        checks["pydantic_ai_circuit_breakers"] = {
            "main_agent": main_cb.get_status(),
            "offer_agent": offer_cb.get_status(),
            "vision_agent": vision_cb.get_status(),
            "payment_agent": payment_cb.get_status(),
        }

        # Check if any agent circuit breaker is OPEN
        if not main_cb.can_execute() or not offer_cb.can_execute():
            status = "degraded"
            logger.warning("Health check: Some PydanticAI agent circuit breakers are OPEN")
    except Exception as e:
        checks["pydantic_ai_circuit_breakers"] = {"status": "error", "error": str(e)[:100]}
        logger.warning("Health check: Failed to check PydanticAI circuit breakers: %s", e)

    return {
        "status": status,
        "checks": checks,
        **_get_build_info(),
        "version": "1.0.0",
        "celery_enabled": settings.CELERY_ENABLED,
        "llm_provider": settings.LLM_PROVIDER,
        "active_model": settings.active_llm_model,
    }


@router.get("/health/graph")
async def health_graph() -> dict[str, Any]:
    """Health check for LangGraph specifically."""
    try:
        from src.agents import get_active_graph
        from src.agents.langgraph.checkpointer import get_checkpointer, is_persistent

        graph = get_active_graph()
        checkpointer = get_checkpointer()

        return {
            "status": "ok",
            "graph_compiled": graph is not None,
            "checkpointer": {
                "initialized": checkpointer is not None,
                "persistent": is_persistent(),
            },
        }
    except Exception as e:
        logger.exception("Graph health check failed: %s", e)
        return {
            "status": "error",
            "error": str(e)[:200],
        }


@router.get("/health/ready")
async def readiness() -> Response:
    """Readiness probe for Kubernetes/deployment systems.
    
    Checks only critical components:
    - Checkpointer (PostgreSQL)
    - LangGraph graph
    - LLM provider availability
    
    Returns:
        HTTP 200 if all critical components are ready
        HTTP 503 if any critical component is not ready
    """
    try:
        from src.server.startup_validation import validate_critical_components
        
        checks = await validate_critical_components()
        
        if checks["all_ready"]:
            return JSONResponse(
                {"status": "ready", "checks": checks["checks"]},
                status_code=200
            )
        else:
            return JSONResponse(
                {
                    "status": "not_ready",
                    "failures": checks["failures"],
                    "checks": checks["checks"],
                },
                status_code=503
            )
    except Exception as e:
        logger.exception("Readiness check failed: %s", e)
        return JSONResponse(
            {
                "status": "not_ready",
                "error": str(e)[:200],
            },
            status_code=503
        )


@router.get("/health/agents")
async def health_agents() -> dict[str, Any]:
    """Health check for PydanticAI agents specifically."""
    try:
        from src.agents.pydantic.main_agent import get_main_agent, get_offer_agent
        from src.agents.pydantic.vision_agent import get_vision_agent
        from src.agents.pydantic.payment_agent import get_payment_agent
        from src.core.circuit_breaker import get_circuit_breaker

        main_agent = get_main_agent()
        offer_agent = get_offer_agent()
        vision_agent = get_vision_agent()
        payment_agent = get_payment_agent()

        main_cb = get_circuit_breaker("pydantic_ai_main_agent")
        offer_cb = get_circuit_breaker("pydantic_ai_offer_agent")
        vision_cb = get_circuit_breaker("pydantic_ai_vision_agent")
        payment_cb = get_circuit_breaker("pydantic_ai_payment_agent")

        return {
            "status": "ok",
            "agents": {
                "main_agent": "available",
                "offer_agent": "available",
                "vision_agent": "available",
                "payment_agent": "available",
            },
            "circuit_breakers": {
                "main_agent": main_cb.get_status(),
                "offer_agent": offer_cb.get_status(),
                "vision_agent": vision_cb.get_status(),
                "payment_agent": payment_cb.get_status(),
            },
        }
    except Exception as e:
        logger.exception("Agents health check failed: %s", e)
        return {
            "status": "error",
            "error": str(e)[:200],
        }
