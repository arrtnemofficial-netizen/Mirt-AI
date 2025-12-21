"""Health check router.

Extracted from main.py to reduce God Object pattern.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter

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

    return {
        "status": status,
        "checks": checks,
        **_get_build_info(),
        "version": "1.0.0",
        "celery_enabled": settings.CELERY_ENABLED,
        "llm_provider": settings.LLM_PROVIDER,
        "active_model": settings.active_llm_model,
    }
