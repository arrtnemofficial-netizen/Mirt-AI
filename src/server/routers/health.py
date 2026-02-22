"""Health check endpoints."""

import logging
from datetime import datetime, timezone
UTC = timezone.utc
from typing import Any

import httpx
from fastapi import APIRouter

from src.conf.config import settings
from src.server.routers.common import get_build_info
from src.server.startup_checks import run_smoke_checks


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint with dependency status."""
    from src.services.storage import health_check as postgres_health_check

    status = "ok"
    checks: dict[str, Any] = {}

    # Перевірка PostgreSQL
    try:
        is_healthy = await postgres_health_check()
        if is_healthy:
            checks["postgresql"] = "ok"
        else:
            checks["postgresql"] = "error"
            status = "degraded"
    except Exception as e:
        checks["postgresql"] = f"error: {type(e).__name__}"
        status = "degraded"
        logger.warning("Health check: PostgreSQL unavailable: %s", e)

    # Перевірка Redis (якщо Celery увімкнено)
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
        from src.services.llm import get_llm_service

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

    # Include LLM configuration in health response
    env = settings.SENTRY_ENVIRONMENT.lower() if settings.SENTRY_ENVIRONMENT else "development"
    has_openai_key = bool(settings.OPENAI_API_KEY.get_secret_value())
    has_openrouter_key = bool(settings.OPENROUTER_API_KEY.get_secret_value())

    return {
        "status": status,
        "checks": checks,
        **get_build_info(),
        "version": "1.0.0",
        "celery_enabled": settings.CELERY_ENABLED,
        "llm_config": {
            "provider": settings.LLM_PROVIDER,
            "ai_model": settings.AI_MODEL,
            "active_model": settings.active_llm_model,
            "env": env,
            "openai_key_set": has_openai_key,
            "openrouter_key_set": has_openrouter_key,
        },
    }


@router.get("/health/observability")
async def health_observability() -> dict[str, Any]:
    """Health check for observability system (llm_traces)."""
    enabled = settings.ENABLE_OBSERVABILITY
    status = "ok" if enabled else "disabled"

    # Check if llm_traces table is accessible using async pool
    try:
        from src.services.storage import get_postgres_pool

        pool = await get_postgres_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM llm_traces WHERE created_at > NOW() - INTERVAL '1 hour'"
            )
            row = await cur.fetchone()
            recent_traces = row[0] if row else 0

        return {
            "status": status,
            "enabled": enabled,
            "recent_traces_1h": recent_traces,
            "message": "llm_traces will be populated"
            if enabled
            else "llm_traces will NOT be populated (ENABLE_OBSERVABILITY=False)",
        }
    except Exception as e:
        return {
            "status": "error",
            "enabled": enabled,
            "error": str(e),
        }


@router.get("/health/memory")
async def health_memory() -> dict[str, Any]:
    """Health check for memory system (mirt_profiles, mirt_memories)."""
    try:
        from src.services.memory import MemoryService
        from src.services.storage import get_postgres_pool

        memory_service = MemoryService()
        enabled = memory_service.enabled

        if not enabled:
            return {
                "status": "disabled",
                "enabled": False,
                "message": "Memory system disabled (DATABASE_URL not configured)",
            }

        # Check tables using async pool
        pool = await get_postgres_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM mirt_profiles WHERE created_at > NOW() - INTERVAL '1 day'"
            )
            row = await cur.fetchone()
            recent_profiles = row[0] if row else 0

            await cur.execute(
                "SELECT COUNT(*) FROM mirt_memories WHERE created_at > NOW() - INTERVAL '1 day'"
            )
            row = await cur.fetchone()
            recent_memories = row[0] if row else 0

        return {
            "status": "ok",
            "enabled": True,
            "recent_profiles_1d": recent_profiles,
            "recent_memories_1d": recent_memories,
            "message": "Memory system enabled - mirt_profiles and mirt_memories will be populated",
        }
    except Exception as e:
        return {
            "status": "error",
            "enabled": False,
            "error": str(e),
        }


@router.get("/health/workers")
async def health_workers() -> dict[str, Any]:
    """Health check for Celery workers and scheduled tasks."""
    if not settings.CELERY_ENABLED:
        return {
            "status": "disabled",
            "celery_enabled": False,
            "message": "Celery disabled - scheduled tasks will NOT run",
        }

    try:
        import redis

        from src.workers.celery_app import celery_app

        # Check Redis
        redis_status = "ok"
        try:
            r = redis.from_url(settings.REDIS_URL)
            r.ping()
        except Exception as e:
            redis_status = f"error: {type(e).__name__}"

        # Check Celery workers
        worker_status = "unknown"
        worker_count = 0
        try:
            inspect = celery_app.control.inspect()
            active = inspect.active()
            if active:
                worker_count = len(active)
                worker_status = "ok"
            else:
                worker_status = "no_workers"
        except Exception as e:
            worker_status = f"error: {type(e).__name__}"

        # Check beat schedule
        beat_schedule = celery_app.conf.beat_schedule or {}
        scheduled_tasks = list(beat_schedule.keys())

        status = "ok" if redis_status == "ok" and worker_status == "ok" else "degraded"

        return {
            "status": status,
            "celery_enabled": True,
            "redis": {"status": redis_status},
            "workers": {
                "status": worker_status,
                "count": worker_count,
            },
            "scheduled_tasks": scheduled_tasks,
            "message": f"Scheduled tasks configured: {', '.join(scheduled_tasks)}"
            if scheduled_tasks
            else "No scheduled tasks configured",
        }
    except Exception as e:
        return {
            "status": "error",
            "celery_enabled": settings.CELERY_ENABLED,
            "error": str(e),
        }


@router.get("/health/smoke")
async def health_smoke() -> dict[str, Any]:
    """Run startup smoke checks outside startup hot path."""
    report = run_smoke_checks()
    return report.to_dict()


@router.get("/health/preflight")
async def health_preflight() -> dict[str, Any]:
    """Comprehensive preflight health check for all systems.

    Returns a unified status report covering:
    - PostgreSQL connection and tables
    - Redis connection
    - Celery workers and beat schedule
    - Memory system status
    - Observability status
    - External APIs (ManyChat, Sitniks)

    Use this endpoint after deployment to verify all systems are operational
    before starting production traffic.
    """
    timestamp = datetime.now(UTC).isoformat()
    checks: dict[str, Any] = {}
    recommendations: list[str] = []
    overall_status = "ok"

    # 1. PostgreSQL check
    try:
        from src.services.storage import get_postgres_pool
        from src.services.storage import health_check as postgres_health_check

        is_healthy = await postgres_health_check()
        if is_healthy:
            # Check critical tables exist using async pool
            pool = await get_postgres_pool()
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name IN ('users', 'messages', 'orders', 'order_items', 'llm_traces', 'mirt_profiles', 'mirt_memories')
                """)
                rows = await cur.fetchall()
                existing_tables = {row[0] for row in rows}

            checks["postgresql"] = {
                "status": "ok",
                "connection": "ok",
                "tables_found": len(existing_tables),
                "critical_tables": list(existing_tables),
            }
        else:
            checks["postgresql"] = {"status": "error", "connection": "failed"}
            overall_status = "critical"
            recommendations.append("PostgreSQL connection failed - check DATABASE_URL")
    except Exception as e:
        checks["postgresql"] = {"status": "error", "error": str(e)}
        overall_status = "critical"
        recommendations.append(f"PostgreSQL check failed: {type(e).__name__}")

    # 2. Redis check
    if settings.CELERY_ENABLED:
        try:
            import redis

            r = redis.from_url(settings.REDIS_URL)
            r.ping()
            checks["redis"] = {"status": "ok", "connection": "ok"}
        except Exception as e:
            checks["redis"] = {"status": "error", "error": type(e).__name__}
            overall_status = "degraded" if overall_status == "ok" else overall_status
            recommendations.append(f"Redis connection failed - check REDIS_URL: {type(e).__name__}")
    else:
        checks["redis"] = {"status": "disabled", "message": "Celery disabled"}

    # 3. Celery workers check
    if settings.CELERY_ENABLED:
        try:
            from src.workers.celery_app import celery_app

            inspect = celery_app.control.inspect()
            active_workers = inspect.active()

            worker_count = len(active_workers) if active_workers else 0
            beat_schedule = celery_app.conf.beat_schedule or {}

            if worker_count > 0:
                checks["celery_workers"] = {
                    "status": "ok",
                    "active_count": worker_count,
                    "queues": list({q.name for q in celery_app.conf.task_queues}),
                }
            else:
                checks["celery_workers"] = {
                    "status": "no_workers",
                    "active_count": 0,
                    "message": "No active workers found - check Worker service on Railway",
                }
                overall_status = "degraded" if overall_status == "ok" else overall_status
                recommendations.append(
                    "No Celery workers active - verify Worker service is running with 'python scripts/run_worker.py'"
                )

            checks["celery_beat"] = {
                "status": "ok" if beat_schedule else "no_schedule",
                "scheduled_tasks": list(beat_schedule.keys()),
                "count": len(beat_schedule),
            }
            if not beat_schedule:
                recommendations.append(
                    "No scheduled tasks configured - verify Beat service is running with 'python scripts/run_beat.py'"
                )
        except Exception as e:
            checks["celery_workers"] = {"status": "error", "error": str(e)}
            checks["celery_beat"] = {"status": "error", "error": str(e)}
            overall_status = "degraded" if overall_status == "ok" else overall_status
    else:
        checks["celery_workers"] = {"status": "disabled", "message": "Celery disabled"}
        checks["celery_beat"] = {"status": "disabled", "message": "Celery disabled"}

    # 4. Memory system check
    try:
        from src.services.memory import MemoryService
        from src.services.storage import get_postgres_pool

        memory_service = MemoryService()
        enabled = memory_service.enabled

        if enabled:
            pool = await get_postgres_pool()
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM mirt_profiles WHERE created_at > NOW() - INTERVAL '1 day'"
                )
                row = await cur.fetchone()
                recent_profiles = row[0] if row else 0
                await cur.execute(
                    "SELECT COUNT(*) FROM mirt_memories WHERE created_at > NOW() - INTERVAL '1 day'"
                )
                row = await cur.fetchone()
                recent_memories = row[0] if row else 0

            checks["memory_system"] = {
                "status": "ok",
                "enabled": True,
                "recent_profiles_1d": recent_profiles,
                "recent_memories_1d": recent_memories,
            }
        else:
            checks["memory_system"] = {
                "status": "disabled",
                "enabled": False,
                "message": "Memory system disabled (DATABASE_URL not configured)",
            }
    except Exception as e:
        checks["memory_system"] = {"status": "error", "error": str(e)}

    # 5. Observability check
    enabled = settings.ENABLE_OBSERVABILITY
    if enabled:
        try:
            from src.services.storage import get_postgres_pool

            pool = await get_postgres_pool()
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM llm_traces WHERE created_at > NOW() - INTERVAL '1 hour'"
                )
                row = await cur.fetchone()
                recent_traces = row[0] if row else 0

            checks["observability"] = {
                "status": "ok",
                "enabled": True,
                "recent_traces_1h": recent_traces,
            }
        except Exception as e:
            checks["observability"] = {"status": "error", "enabled": True, "error": str(e)}
    else:
        checks["observability"] = {
            "status": "disabled",
            "enabled": False,
            "message": "Observability disabled (ENABLE_OBSERVABILITY=False) - llm_traces will NOT be populated",
        }
        recommendations.append("Set ENABLE_OBSERVABILITY=true to enable llm_traces logging")

    # 6. External APIs (non-blocking, quick checks)
    checks["external_apis"] = {}

    # ManyChat
    if settings.MANYCHAT_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                # Simple check - ManyChat may not have /status, so we just check if we can reach it
                await client.get(settings.MANYCHAT_API_URL, timeout=3.0)
                checks["external_apis"]["manychat"] = {"status": "ok", "reachable": True}
        except Exception as e:
            checks["external_apis"]["manychat"] = {"status": "warning", "error": type(e).__name__}
    else:
        checks["external_apis"]["manychat"] = {
            "status": "not_configured",
            "message": "MANYCHAT_API_KEY not set",
        }

    # Sitniks
    if settings.SNITKIX_API_KEY and settings.ENABLE_CRM_INTEGRATION:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.get(settings.SNITKIX_API_URL, timeout=3.0)
                checks["external_apis"]["sitniks"] = {"status": "ok", "reachable": True}
        except Exception as e:
            checks["external_apis"]["sitniks"] = {"status": "warning", "error": type(e).__name__}
    elif settings.ENABLE_CRM_INTEGRATION:
        checks["external_apis"]["sitniks"] = {
            "status": "not_configured",
            "message": "SNITKIX_API_KEY not set but ENABLE_CRM_INTEGRATION=true",
        }
    else:
        checks["external_apis"]["sitniks"] = {
            "status": "disabled",
            "message": "CRM integration disabled",
        }

    return {
        "status": overall_status,
        "timestamp": timestamp,
        "checks": checks,
        "recommendations": recommendations,
        "summary": {
            "all_systems_operational": overall_status == "ok",
            "critical_issues": len(
                [r for r in recommendations if "critical" in r.lower() or "failed" in r.lower()]
            ),
            "warnings": len(
                [
                    r
                    for r in recommendations
                    if "warning" in r.lower() or "not configured" in r.lower()
                ]
            ),
        },
        **get_build_info(),
    }
