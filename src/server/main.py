"""ASGI app exposing Telegram and ManyChat webhooks.

This module uses proper FastAPI dependency injection and lifespan management
instead of global singletons.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

import httpx
from aiogram.types import Update
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from starlette.responses import StreamingResponse

from src.conf.config import settings
from src.core.logging import log_event, safe_preview, setup_logging
from src.integrations.manychat.webhook import ManychatPayloadError
from src.server.dependencies import (
    MessageStoreDep,
    get_bot,
    get_cached_dispatcher,
    get_cached_manychat_handler,
)
from src.server.middleware import setup_middleware
from src.services.webhook import WebhookDedupeStore


logger = logging.getLogger(__name__)


# Will be initialized in webhook handler


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


def _extract_manychat_message_id(payload: dict[str, Any], message: dict[str, Any]) -> str | None:
    # Prefer explicit message ids if present. If absent, we do NOT dedupe
    # to avoid false positives on repeated user texts.
    for key in ("id", "message_id", "messageId"):
        value = message.get(key)
        if value:
            return str(value)

    for key in ("message_id", "messageId", "event_id", "eventId", "update_id", "updateId"):
        value = payload.get(key)
        if value:
            return str(value)

    return None


def _init_sentry():
    """Initialize Sentry SDK if configured."""
    if not settings.SENTRY_DSN:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            integrations=[
                FastApiIntegration(),
                CeleryIntegration(),
            ],
            send_default_pii=False,
        )
        logger.info("Sentry initialized: env=%s", settings.SENTRY_ENVIRONMENT)
    except ImportError:
        logger.warning("sentry-sdk not installed, skipping Sentry init")
    except Exception as e:
        logger.error("Failed to initialize Sentry: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown events."""
    # Initialize Sentry first
    _init_sentry()

    # Configure logging (JSON in production, pretty in development)
    is_production = settings.PUBLIC_BASE_URL != "http://localhost:8000"
    setup_logging(
        level="INFO",
        json_format=is_production,
        service_name="mirt-ai",
    )

    # Startup banner
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                  MIRT AI - WEBHOOK SERVER                   ║
║                  Production API Service                      ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)
    logger.info("=" * 60)
    logger.info("MIRT AI Webhooks Server Starting")
    logger.info("=" * 60)
    
    build_info = _get_build_info()
    logger.info(
        "Build info: git_sha=%s build_id=%s",
        build_info.get("git_sha"),
        build_info.get("build_id"),
    )
    
    # Log LLM configuration (critical for production verification)
    env = settings.SENTRY_ENVIRONMENT.lower() if settings.SENTRY_ENVIRONMENT else "development"
    has_openai_key = bool(settings.OPENAI_API_KEY.get_secret_value())
    has_openrouter_key = bool(settings.OPENROUTER_API_KEY.get_secret_value())
    
    logger.info(
        "LLM Configuration: AI_MODEL=%s, LLM_PROVIDER=%s, env=%s, "
        "OPENAI_API_KEY=%s, OPENROUTER_API_KEY=%s",
        settings.AI_MODEL,
        settings.LLM_PROVIDER,
        env,
        "set" if has_openai_key else "missing",
        "set" if has_openrouter_key else "missing",
    )
    
    # Log Observability status
    logger.info(
        "Observability: ENABLE_OBSERVABILITY=%s (llm_traces will %s)",
        settings.ENABLE_OBSERVABILITY,
        "be populated" if settings.ENABLE_OBSERVABILITY else "NOT be populated",
    )
    
    # Log Memory System status
    try:
        from src.services.memory_service import MemoryService
        memory_service = MemoryService()
        logger.info(
            "Memory System: enabled=%s (mirt_profiles, mirt_memories will %s)",
            memory_service.enabled,
            "be populated" if memory_service.enabled else "NOT be populated",
        )
    except Exception as e:
        logger.warning("Memory System: failed to check status: %s", e)
    
    # Log Celery status
    if settings.CELERY_ENABLED:
        logger.info(
            "Celery: enabled=%s, REDIS_URL=%s (scheduled tasks will run)",
            settings.CELERY_ENABLED,
            "configured" if settings.REDIS_URL else "missing",
        )
    else:
        logger.warning("Celery: disabled (scheduled tasks will NOT run)")
    
    # Validate model configuration in production
    if env in ("production", "prod", "staging"):
        if settings.LLM_PROVIDER == "openai" and not has_openai_key:
            logger.error(
                "CRITICAL: OPENAI_API_KEY is missing in %s environment. "
                "LLM calls will fail. Set OPENAI_API_KEY environment variable.",
                env,
            )
        if settings.AI_MODEL != "gpt-5.1":
            logger.warning(
                "AI_MODEL is set to '%s' (expected 'gpt-5.1' in production). "
                "Update AI_MODEL environment variable if this is incorrect.",
                settings.AI_MODEL,
            )

    # ==========================================================================
    # WARMUP: Pre-initialize the graph to avoid 20+ second delay on first request
    # This is CRITICAL for ManyChat timeout compliance
    # ==========================================================================
    try:
        from src.agents.langgraph import get_production_graph
        from src.agents.langgraph.checkpointer import warmup_checkpointer_pool

        logger.info("Warming up LangGraph (this may take 10-20 seconds on first deploy)...")
        _graph = get_production_graph()
        warmup_ok = await warmup_checkpointer_pool()
        if not warmup_ok:
            required = (
                (os.getenv("CHECKPOINTER_WARMUP_REQUIRED", "false") or "false").strip().lower()
            )
            if required in {"1", "true", "yes"}:
                raise RuntimeError("Checkpointer warmup required but failed")
            logger.warning("LangGraph warmup incomplete; continuing without warm pool")
        else:
            logger.info("LangGraph warmed up successfully!")
    except Exception as e:
        logger.warning("Failed to warm up LangGraph: %s (will initialize on first request)", e)

    # Telegram webhook: ОТКЛЮЧЕНО - Telegram используется ТОЛЬКО для уведомлений менеджера
    # Клиенты общаются через ManyChat/Instagram, не через Telegram
    # Если нужно включить Telegram как канал для клиентов, используй ENABLE_TELEGRAM_WEBHOOK=true
    enable_telegram_webhook = os.getenv("ENABLE_TELEGRAM_WEBHOOK", "false").lower() == "true"
    
    if enable_telegram_webhook:
        base_url = settings.PUBLIC_BASE_URL.rstrip("/")
        token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
        if base_url and token:
            try:
                bot = get_bot()
                full_url = f"{base_url}{settings.TELEGRAM_WEBHOOK_PATH}"
                await bot.set_webhook(full_url)
                logger.info("Telegram webhook registered: %s", full_url)
            except Exception as e:
                logger.error("Failed to register Telegram webhook: %s", e)
    else:
        logger.info("Telegram webhook disabled - Telegram is used ONLY for manager notifications")

    # Check external services (non-blocking, with timeouts)
    logger.info("Checking external services...")
    
    # Check ManyChat API
    if settings.MANYCHAT_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{settings.MANYCHAT_API_URL}/status",
                    headers={"Authorization": f"Bearer {settings.MANYCHAT_API_KEY}"},
                )
                if response.status_code == 200:
                    logger.info("✓ ManyChat API: accessible")
                else:
                    logger.warning("⚠ ManyChat API: returned status %s", response.status_code)
        except Exception as e:
            logger.warning("⚠ ManyChat API: check failed (%s) - will retry on first request", type(e).__name__)
    else:
        logger.warning("⚠ ManyChat API: API key not configured")
    
    # Check Sitniks API
    if settings.SNITKIX_API_KEY and settings.ENABLE_CRM_INTEGRATION:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Simple health check - adjust endpoint if needed
                response = await client.get(
                    f"{settings.SNITKIX_API_URL}/health",
                    headers={"Authorization": f"Bearer {settings.SNITKIX_API_KEY}"},
                )
                if response.status_code in (200, 404):  # 404 is OK if endpoint doesn't exist
                    logger.info("✓ Sitniks API: accessible")
                else:
                    logger.warning("⚠ Sitniks API: returned status %s", response.status_code)
        except httpx.TimeoutException:
            logger.warning("⚠ Sitniks API: timeout - will retry on first request")
        except Exception as e:
            logger.warning("⚠ Sitniks API: check failed (%s) - will retry on first request", type(e).__name__)
    elif settings.ENABLE_CRM_INTEGRATION:
        logger.warning("⚠ Sitniks API: API key not configured (CRM integration enabled)")
    
    logger.info("=" * 60)
    logger.info("Server ready! All systems operational.")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("Shutting down MIRT AI Webhooks server")
    
    # Gracefully close checkpointer pool
    try:
        from src.agents.langgraph.checkpointer import shutdown_checkpointer_pool
        await shutdown_checkpointer_pool()
    except Exception as e:
        logger.warning("Failed to shutdown checkpointer pool: %s", e)


app = FastAPI(
    title="MIRT AI Webhooks",
    description="AI-powered shopping assistant webhooks for Telegram and ManyChat",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/media/proxy")
async def media_proxy(url: str, token: str | None = None) -> StreamingResponse:
    if not bool(getattr(settings, "MEDIA_PROXY_ENABLED", False)):
        raise HTTPException(status_code=404, detail="disabled")

    required_token = str(getattr(settings, "MEDIA_PROXY_TOKEN", "") or "").strip()
    if required_token and (token or "") != required_token:
        raise HTTPException(status_code=401, detail="invalid token")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="invalid url")

    host = (parsed.hostname or "").lower()
    allowed_hosts_raw = str(getattr(settings, "MEDIA_PROXY_ALLOWED_HOSTS", "") or "")
    allowed_hosts = {h.strip().lower() for h in allowed_hosts_raw.split(",") if h and h.strip()}
    if allowed_hosts and host not in allowed_hosts:
        raise HTTPException(status_code=403, detail="host not allowed")

    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        upstream = await client.get(url)

    if upstream.status_code != 200:
        raise HTTPException(status_code=502, detail=f"upstream {upstream.status_code}")

    content_type = upstream.headers.get("content-type") or "application/octet-stream"
    if not content_type.lower().startswith("image/"):
        raise HTTPException(status_code=415, detail="not an image")

    data = upstream.content
    if len(data) > 8_000_000:
        raise HTTPException(status_code=413, detail="too large")

    headers = {
        "Cache-Control": "public, max-age=3600",
    }
    return StreamingResponse(iter([data]), media_type=content_type, headers=headers)


# Setup middleware (rate limiting, request logging)
setup_middleware(app, enable_rate_limit=True, enable_logging=True)


# Regex to detect image URLs in message text
# Supports:
# - Direct image URLs (.jpg, .png, etc.)
# - Instagram CDN: cdn.instagram.com, fbcdn, scontent
# - Instagram DM images: lookaside.fbsbx.com/ig_messaging_cdn
_IMAGE_URL_PATTERN = re.compile(
    r"(https?://[^\s]+\.(?:jpg|jpeg|png|gif|webp|bmp|svg)|"
    r"https?://(?:cdn\.)?(?:instagram|fbcdn|scontent|lookaside\.fbsbx)[^\s]+)",
    re.IGNORECASE,
)


class ApiV1MessageRequest(BaseModel):
    """Request model for /api/v1/messages endpoint.

    Supports multiple formats:
    - ManyChat External Request: {type, clientId, message, image_url}
    - n8n format: {sessionId, name, message} where message may contain image URL
    """

    type: str = Field(default="instagram")
    message: str = Field(default="", validation_alias=AliasChoices("message", "messages"))
    client_id: str = Field(
        validation_alias=AliasChoices("clientId", "client_id", "sessionId", "session_id"),
        serialization_alias="clientId",
    )
    client_name: str = Field(
        default="",
        validation_alias=AliasChoices("clientName", "client_name", "name"),
        serialization_alias="clientName",
    )
    username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("username", "userName", "user_name"),
        serialization_alias="username",
    )
    image_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "image_url",
            "imageUrl",
            "photo_url",
            "photoUrl",
            "image",
            "photo",
        ),
        serialization_alias="image_url",
    )

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="ignore")

    @model_validator(mode="after")
    def extract_image_from_message(self) -> ApiV1MessageRequest:
        """Extract image URL from message text if not provided separately.

        This handles the n8n format where message field contains the image URL.
        Also strips ManyChat/n8n prefix '.;' from messages.
        """
        msg = (self.message or "").strip()
        img_url = self.image_url

        # Strip ManyChat/n8n prefix '.;' (can appear multiple times)
        while msg.startswith(".;"):
            msg = msg[2:].lstrip()

        # Extract image URL from message text if not provided separately
        if not img_url and msg:
            match = _IMAGE_URL_PATTERN.search(msg)
            if match:
                img_url = match.group(0)
                logger.info("[API_V1] 📷 Extracted image URL from message: %s", img_url[:60])

        # Remove embedded image URL from message text
        if img_url and msg:
            msg = msg.replace(img_url, "").strip()
            # Strip prefix again in case it was before the URL
            while msg.startswith(".;"):
                msg = msg[2:].lstrip()

        if not msg and not img_url:
            raise ValueError("Either message or image_url is required")

        # Use object.__setattr__ for Pydantic v2 compatibility
        object.__setattr__(self, "message", msg)
        object.__setattr__(self, "image_url", img_url)
        return self


@app.get("/health")
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
        **_get_build_info(),
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


@app.get("/health/observability")
async def health_observability() -> dict[str, Any]:
    """Health check for observability system (llm_traces)."""
    enabled = settings.ENABLE_OBSERVABILITY
    status = "ok" if enabled else "disabled"
    
    # Check if llm_traces table is accessible
    try:
        from src.services.storage import get_postgres_url
        import psycopg
        
        postgres_url = get_postgres_url()
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM llm_traces WHERE created_at > NOW() - INTERVAL '1 hour'")
                recent_traces = cur.fetchone()[0]
        
        return {
            "status": status,
            "enabled": enabled,
            "recent_traces_1h": recent_traces,
            "message": "llm_traces will be populated" if enabled else "llm_traces will NOT be populated (ENABLE_OBSERVABILITY=False)",
        }
    except Exception as e:
        return {
            "status": "error",
            "enabled": enabled,
            "error": str(e),
        }


@app.get("/health/memory")
async def health_memory() -> dict[str, Any]:
    """Health check for memory system (mirt_profiles, mirt_memories)."""
    try:
        from src.services.memory_service import MemoryService
        from src.services.storage import get_postgres_url
        import psycopg
        
        memory_service = MemoryService()
        enabled = memory_service.enabled
        
        if not enabled:
            return {
                "status": "disabled",
                "enabled": False,
                "message": "Memory system disabled (DATABASE_URL not configured)",
            }
        
        # Check tables
        postgres_url = get_postgres_url()
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM mirt_profiles WHERE created_at > NOW() - INTERVAL '1 day'")
                recent_profiles = cur.fetchone()[0]
                
                cur.execute("SELECT COUNT(*) FROM mirt_memories WHERE created_at > NOW() - INTERVAL '1 day'")
                recent_memories = cur.fetchone()[0]
        
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


@app.get("/health/workers")
async def health_workers() -> dict[str, Any]:
    """Health check for Celery workers and scheduled tasks."""
    if not settings.CELERY_ENABLED:
        return {
            "status": "disabled",
            "celery_enabled": False,
            "message": "Celery disabled - scheduled tasks will NOT run",
        }
    
    try:
        from src.workers.celery_app import celery_app
        import redis
        
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
            "message": f"Scheduled tasks configured: {', '.join(scheduled_tasks)}" if scheduled_tasks else "No scheduled tasks configured",
        }
    except Exception as e:
        return {
            "status": "error",
            "celery_enabled": settings.CELERY_ENABLED,
            "error": str(e),
        }


@app.get("/health/preflight")
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
    from datetime import UTC, datetime
    
    timestamp = datetime.now(UTC).isoformat()
    checks: dict[str, Any] = {}
    recommendations: list[str] = []
    overall_status = "ok"
    
    # 1. PostgreSQL check
    try:
        from src.services.storage import health_check as postgres_health_check, get_postgres_url
        import psycopg
        
        is_healthy = await postgres_health_check()
        if is_healthy:
            # Check critical tables exist
            postgres_url = get_postgres_url()
            with psycopg.connect(postgres_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name IN ('users', 'messages', 'orders', 'order_items', 'llm_traces', 'mirt_profiles', 'mirt_memories')
                    """)
                    existing_tables = {row[0] for row in cur.fetchall()}
            
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
            scheduled_tasks = inspect.scheduled()
            
            worker_count = len(active_workers) if active_workers else 0
            beat_schedule = celery_app.conf.beat_schedule or {}
            
            if worker_count > 0:
                checks["celery_workers"] = {
                    "status": "ok",
                    "active_count": worker_count,
                    "queues": list(set([q.name for q in celery_app.conf.task_queues])),
                }
            else:
                checks["celery_workers"] = {
                    "status": "no_workers",
                    "active_count": 0,
                    "message": "No active workers found - check Worker service on Railway",
                }
                overall_status = "degraded" if overall_status == "ok" else overall_status
                recommendations.append("No Celery workers active - verify Worker service is running with 'python scripts/run_worker.py'")
            
            checks["celery_beat"] = {
                "status": "ok" if beat_schedule else "no_schedule",
                "scheduled_tasks": list(beat_schedule.keys()),
                "count": len(beat_schedule),
            }
            if not beat_schedule:
                recommendations.append("No scheduled tasks configured - verify Beat service is running with 'python scripts/run_beat.py'")
        except Exception as e:
            checks["celery_workers"] = {"status": "error", "error": str(e)}
            checks["celery_beat"] = {"status": "error", "error": str(e)}
            overall_status = "degraded" if overall_status == "ok" else overall_status
    else:
        checks["celery_workers"] = {"status": "disabled", "message": "Celery disabled"}
        checks["celery_beat"] = {"status": "disabled", "message": "Celery disabled"}
    
    # 4. Memory system check
    try:
        from src.services.memory_service import MemoryService
        import psycopg
        from src.services.storage import get_postgres_url
        
        memory_service = MemoryService()
        enabled = memory_service.enabled
        
        if enabled:
            postgres_url = get_postgres_url()
            with psycopg.connect(postgres_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM mirt_profiles WHERE created_at > NOW() - INTERVAL '1 day'")
                    recent_profiles = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM mirt_memories WHERE created_at > NOW() - INTERVAL '1 day'")
                    recent_memories = cur.fetchone()[0]
            
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
            import psycopg
            from src.services.storage import get_postgres_url
            
            postgres_url = get_postgres_url()
            with psycopg.connect(postgres_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM llm_traces WHERE created_at > NOW() - INTERVAL '1 hour'")
                    recent_traces = cur.fetchone()[0]
            
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
                response = await client.get(settings.MANYCHAT_API_URL, timeout=3.0)
                checks["external_apis"]["manychat"] = {"status": "ok", "reachable": True}
        except Exception as e:
            checks["external_apis"]["manychat"] = {"status": "warning", "error": type(e).__name__}
    else:
        checks["external_apis"]["manychat"] = {"status": "not_configured", "message": "MANYCHAT_API_KEY not set"}
    
    # Sitniks
    if settings.SNITKIX_API_KEY and settings.ENABLE_CRM_INTEGRATION:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(settings.SNITKIX_API_URL, timeout=3.0)
                checks["external_apis"]["sitniks"] = {"status": "ok", "reachable": True}
        except Exception as e:
            checks["external_apis"]["sitniks"] = {"status": "warning", "error": type(e).__name__}
    elif settings.ENABLE_CRM_INTEGRATION:
        checks["external_apis"]["sitniks"] = {"status": "not_configured", "message": "SNITKIX_API_KEY not set but ENABLE_CRM_INTEGRATION=true"}
    else:
        checks["external_apis"]["sitniks"] = {"status": "disabled", "message": "CRM integration disabled"}
    
    return {
        "status": overall_status,
        "timestamp": timestamp,
        "checks": checks,
        "recommendations": recommendations,
        "summary": {
            "all_systems_operational": overall_status == "ok",
            "critical_issues": len([r for r in recommendations if "critical" in r.lower() or "failed" in r.lower()]),
            "warnings": len([r for r in recommendations if "warning" in r.lower() or "not configured" in r.lower()]),
        },
    }


# Telegram webhook endpoint: ОТКЛЮЧЕНО по умолчанию
# Telegram используется ТОЛЬКО для уведомлений менеджера (через NotificationService)
# Если нужно включить Telegram как канал для клиентов, установи ENABLE_TELEGRAM_WEBHOOK=true
if os.getenv("ENABLE_TELEGRAM_WEBHOOK", "false").lower() == "true":
    @app.post(settings.TELEGRAM_WEBHOOK_PATH)
    async def telegram_webhook(request: Request) -> JSONResponse:
        """Handle incoming Telegram webhook updates (AI-only відповіді).
        
        WARNING: This endpoint is disabled by default. Telegram is used ONLY for manager notifications.
        To enable Telegram as a client channel, set ENABLE_TELEGRAM_WEBHOOK=true.
        """
        bot = get_bot()
        dp = get_cached_dispatcher()

        body = await request.json()
        update = Update.model_validate(body)
        await dp.feed_update(bot=bot, update=update)
        return JSONResponse({"ok": True})
else:
    @app.post(settings.TELEGRAM_WEBHOOK_PATH)
    async def telegram_webhook_disabled(request: Request) -> JSONResponse:
        """Telegram webhook is disabled. Telegram is used ONLY for manager notifications."""
        logger.warning("Telegram webhook called but disabled - Telegram is for manager notifications only")
        return JSONResponse({"ok": False, "error": "Telegram webhook disabled"}, status_code=404)


@app.post("/api/v1/messages", status_code=202)
async def api_v1_messages(
    request: Request,
    background_tasks: BackgroundTasks,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Handle messages from ManyChat External Request.

    Supports formats:
    - {type, clientId, message, image_url}
    - {sessionId, name, message} (n8n format)
    """
    raw_body = await request.body()
    log_event(
        logger,
        event="api_v1_payload_received",
        text_len=len(raw_body or b""),
        text_preview=safe_preview(raw_body.decode("utf-8", errors="replace"), 200),
    )

    import json

    try:
        raw_json = json.loads(raw_body)
        logger.debug("[API_V1] RAW keys=%s", list(raw_json.keys()))
    except json.JSONDecodeError as e:
        log_event(
            logger,
            event="api_v1_payload_parsed",
            level="warning",
            root_cause="INVALID_JSON",
            error=safe_preview(e, 200),
        )
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    try:
        payload = ApiV1MessageRequest.model_validate(raw_json)
        log_event(
            logger,
            event="api_v1_payload_parsed",
            user_id=str(payload.client_id),
            channel=payload.type or "instagram",
            text_len=len(payload.message or ""),
            text_preview=safe_preview(payload.message, 160),
            has_image=bool(payload.image_url),
            image_url_preview=safe_preview(payload.image_url, 100),
        )
    except Exception as e:
        logger.error("[API_V1] ❌ Pydantic validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    # === STEP 3: Auth check ===
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    inbound_token = x_api_key
    if not inbound_token and authorization:
        auth_value = authorization.strip()
        if auth_value.lower().startswith("bearer "):
            inbound_token = auth_value[7:].strip()
        else:
            inbound_token = auth_value

    if verify_token and verify_token != inbound_token:
        logger.warning(
            "[API_V1] ⛔ Auth failed: expected=%s, got=%s",
            verify_token[:10] if verify_token else None,
            inbound_token[:10] if inbound_token else None,
        )
        raise HTTPException(status_code=401, detail="Invalid API token")

    # === STEP 4: Schedule background processing ===
    from src.integrations.manychat.async_service import get_manychat_async_service
    from src.server.dependencies import get_session_store

    store = get_session_store()
    service = get_manychat_async_service(store)

    user_id = str(payload.client_id)
    channel = payload.type or "instagram"

    trace_id = str(uuid.uuid4())

    log_event(
        logger,
        event="api_v1_task_scheduled",
        trace_id=trace_id,
        user_id=user_id,
        channel=channel,
        text_len=len(payload.message or ""),
        text_preview=safe_preview(payload.message, 160),
        has_image=bool(payload.image_url),
        image_url_preview=safe_preview(payload.image_url, 100),
    )

    background_tasks.add_task(
        service.process_message_async,
        user_id=user_id,
        text=payload.message or "",
        image_url=payload.image_url,
        channel=channel,
        trace_id=trace_id,
    )

    logger.debug("[API_V1] returning 202")
    return {"status": "accepted"}


@app.post("/webhooks/manychat")
async def manychat_webhook(
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
    x_manychat_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Handle incoming ManyChat webhook payloads.

    Supports two modes:
    - Push mode (MANYCHAT_PUSH_MODE=true): Returns 202 immediately, processes async
    - Response mode (MANYCHAT_PUSH_MODE=false): Waits for AI, returns response
    """
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    inbound_token = x_manychat_token
    if not inbound_token and authorization:
        auth_value = authorization.strip()
        if auth_value.lower().startswith("bearer "):
            inbound_token = auth_value[7:].strip()
        else:
            inbound_token = auth_value

    if verify_token and verify_token != inbound_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    # Push mode: return immediately, process in background
    if settings.MANYCHAT_PUSH_MODE:
        from src.integrations.manychat.async_service import get_manychat_async_service
        from src.server.dependencies import get_session_store

        try:
            trace_id = str(uuid.uuid4())

            # Extract user info from payload
            subscriber = payload.get("subscriber") or payload.get("user") or {}
            message = payload.get("message") or payload.get("data", {}).get("message") or {}

            user_id = str(subscriber.get("id") or subscriber.get("user_id") or "unknown")
            text = ""
            image_url = None

            if isinstance(message, dict):
                text = message.get("text") or message.get("content") or ""
                # Extract image from attachments
                for attachment in message.get("attachments", []):
                    if attachment.get("type") == "image":
                        image_url = attachment.get("payload", {}).get("url")
                        break
                if not image_url:
                    image_url = message.get("image") or message.get("image_url")

            # Also check data.image_url
            if not image_url:
                data = payload.get("data", {})
                image_url = data.get("image_url") or data.get("photo_url")

            channel = payload.get("type") or "instagram"

            if not text and not image_url:
                raise HTTPException(status_code=400, detail="Missing message text or image")

            # -----------------------------------------------------------------
            # IDEMPOTENCY (DB-backed, 24h TTL)
            # -----------------------------------------------------------------
            message_id = None
            if isinstance(message, dict):
                message_id = _extract_manychat_message_id(payload, message)

            if message_id:
                # Use PostgreSQL for webhook deduplication
                dedupe_store = WebhookDedupeStore(db=None, ttl_hours=24, use_postgres=True)

                if dedupe_store:
                    # Check for duplicates using DB store
                    is_duplicate = dedupe_store.check_and_mark(
                        user_id=user_id,
                        message_id=message_id,
                        text=text,
                        image_url=image_url,
                    )

                    if is_duplicate:
                        logger.info(
                            "[MANYCHAT] Duplicate delivery ignored (push mode) user=%s message_id=%s",
                            user_id,
                            message_id,
                        )
                        return {"status": "accepted"}
                else:
                    logger.warning(
                        "[MANYCHAT] Database disabled, skipping dedupe (push mode) user=%s message_id=%s",
                        user_id,
                        message_id,
                    )

            # -----------------------------------------------------------------
            # BACKGROUND PROCESSING (FastAPI BackgroundTasks)
            # -----------------------------------------------------------------
            # Note: Celery is only used for followups and summarization.
            # ManyChat message processing uses BackgroundTasks for simplicity.
            store = get_session_store()
            service = get_manychat_async_service(store)

            background_tasks.add_task(
                service.process_message_async,
                user_id=user_id,
                text=text or "",
                image_url=image_url,
                channel=channel,
                subscriber_data=subscriber,  # Pass subscriber data for username
                trace_id=trace_id,
            )

            log_event(
                logger,
                event="manychat_task_scheduled",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
                status="background_tasks",
            )

            log_event(
                logger,
                event="manychat_message_accepted",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
            )
            return {"status": "accepted"}

        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[MANYCHAT] Error in push mode: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Response mode: wait for AI and return response
    handler = get_cached_manychat_handler()
    try:
        return await handler.handle(payload)
    except ManychatPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# =============================================================================
# SNITKIX CRM WEBHOOK ENDPOINTS
# =============================================================================


@app.post("/webhooks/snitkix/order-status")
async def snitkix_order_status_webhook(request: Request) -> JSONResponse:
    """Handle order status updates from Snitkix CRM."""
    from src.integrations.crm.webhooks import snitkix_order_status_webhook as webhook_handler

    return await webhook_handler(request)


@app.post("/webhooks/snitkix/payment")
async def snitkix_payment_webhook(request: Request) -> JSONResponse:
    """Handle payment confirmation from Snitkix CRM."""
    from src.integrations.crm.webhooks import snitkix_payment_webhook as webhook_handler

    return await webhook_handler(request)


@app.post("/webhooks/snitkix/inventory")
async def snitkix_inventory_webhook(request: Request) -> JSONResponse:
    """Handle inventory updates from Snitkix CRM."""
    from src.integrations.crm.webhooks import snitkix_inventory_webhook as webhook_handler

    return await webhook_handler(request)


# =============================================================================
# SITNIKS STATUS UPDATE ENDPOINT (for external JS node / n8n / ManyChat)
# =============================================================================


class SitniksUpdateRequest(BaseModel):
    """Request for updating Sitniks chat status from external systems."""

    stage: str = Field(description="Stage: first_touch, give_requisites, escalation")
    user_id: str = Field(
        description="MIRT user/session ID",
        validation_alias=AliasChoices(
            "user_id", "userId", "session_id", "sessionId", "client_id", "clientId"
        ),
    )
    instagram_username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("instagram_username", "instagramUsername", "ig_username"),
    )
    telegram_username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("telegram_username", "telegramUsername", "tg_username"),
    )

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


@app.post("/api/v1/sitniks/update-status")
async def sitniks_update_status(
    payload: SitniksUpdateRequest,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Update Sitniks CRM chat status from external JS node.

    This endpoint allows ManyChat/n8n JS nodes to trigger status updates
    after the agent response is generated.

    Stages:
    - first_touch: Set "Взято в роботу" + assign AI Manager
    - give_requisites: Set "Виставлено рахунок"
    - escalation: Set "AI Увага" + assign human manager

    Auth: X-API-Key header or Authorization: Bearer token
    (uses MANYCHAT_VERIFY_TOKEN)

    Example JS (n8n):
    ```javascript
    const response = await fetch('https://your-server/api/v1/sitniks/update-status', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-API-Key': 'your-token'
        },
        body: JSON.stringify({
            stage: 'first_touch',
            user_id: '12345',
            instagram_username: 'user123'
        })
    });
    ```
    """
    from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service

    # Auth check (same as /api/v1/messages)
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    inbound_token = x_api_key
    if not inbound_token and authorization:
        auth_value = authorization.strip()
        if auth_value.lower().startswith("bearer "):
            inbound_token = auth_value[7:].strip()
        else:
            inbound_token = auth_value

    if verify_token and verify_token != inbound_token:
        raise HTTPException(status_code=401, detail="Invalid API token")

    service = get_sitniks_chat_service()

    if not service.enabled:
        return {
            "success": False,
            "error": "Sitniks integration not configured",
            "stage": payload.stage,
        }

    stage = payload.stage.lower().replace("-", "_").replace(" ", "_")
    user_id = payload.user_id

    logger.info(
        "[SITNIKS_API] Update status: stage=%s, user_id=%s, ig=%s",
        stage,
        user_id,
        payload.instagram_username,
    )

    try:
        if stage == "first_touch":
            result = await service.handle_first_touch(
                user_id=user_id,
                instagram_username=payload.instagram_username,
                telegram_username=payload.telegram_username,
            )
            return {
                "success": result.get("success", False),
                "stage": stage,
                "chat_id": result.get("chat_id"),
                "status_set": result.get("status_set", False),
                "manager_assigned": result.get("manager_assigned", False),
                "error": result.get("error"),
            }

        elif stage in ("give_requisites", "invoice", "invoice_sent"):
            success = await service.handle_invoice_sent(user_id)
            return {
                "success": success,
                "stage": "give_requisites",
            }

        elif stage == "escalation":
            result = await service.handle_escalation(user_id)
            return {
                "success": result.get("success", False),
                "stage": stage,
                "chat_id": result.get("chat_id"),
                "status_set": result.get("status_set", False),
                "manager_assigned": result.get("manager_assigned", False),
            }

        else:
            return {
                "success": False,
                "error": f"Unknown stage: {stage}. Valid: first_touch, give_requisites, escalation",
            }

    except Exception as e:
        logger.exception("[SITNIKS_API] Error: %s", e)
        return {
            "success": False,
            "error": str(e),
            "stage": stage,
        }


@app.post("/automation/mirt-summarize-prod-v1")
async def run_summarization(
    payload: dict[str, Any],
    message_store: MessageStoreDep,
) -> dict[str, Any]:
    """Summarize and prune old messages for a session.

    Called by ManyChat after 3 days of inactivity.
    Saves summary to users.summary and deletes messages from messages table.

    Uses Celery if CELERY_ENABLED=true, otherwise runs synchronously.

    Payload:
    {
        "user_id": 12345,
        "session_id": "12345",
        "action": "summarize"
    }
    """
    from src.workers.dispatcher import dispatch_summarization

    session_id = payload.get("session_id")
    user_id = payload.get("user_id")

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # Convert user_id to int if provided
    user_id_int = int(user_id) if user_id else None

    # Use dispatcher - routes to Celery or sync based on CELERY_ENABLED
    result = dispatch_summarization(session_id, user_id_int)

    if result.get("queued"):
        return {
            "session_id": session_id,
            "user_id": user_id,
            "status": "queued",
            "task_id": result.get("task_id"),
            "action": "remove_tags",
        }

    return {
        "session_id": session_id,
        "user_id": user_id,
        "summary": result.get("summary"),
        "action": "remove_tags",
        "status": "ok",
    }


@app.post("/automation/mirt-followups-prod-v1")
async def trigger_followups(
    payload: dict[str, Any],
    message_store: MessageStoreDep,
) -> dict[str, Any]:
    """Trigger follow-up messages for inactive sessions.

    Uses Celery if CELERY_ENABLED=true, otherwise runs synchronously.
    """
    from src.workers.dispatcher import dispatch_followup

    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # Use dispatcher - routes to Celery or sync based on CELERY_ENABLED
    result = dispatch_followup(session_id)

    if result.get("queued"):
        return {
            "session_id": session_id,
            "status": "queued",
            "task_id": result.get("task_id"),
        }

    return {
        "session_id": session_id,
        "followup_created": result.get("followup_created", False),
        "content": result.get("content"),
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# ManyChat Follow-up Endpoint
# ---------------------------------------------------------------------------
@app.post("/webhooks/manychat/followup")
async def manychat_followup(
    payload: dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
    message_store: MessageStoreDep = None,
) -> dict[str, Any]:
    """ManyChat follow-up endpoint called after Smart Delay.

    This endpoint checks if the user has responded since the last AI message.
    If not, it generates a follow-up message.

    ManyChat Conditions can check:
    - needs_followup: true/false
    - followup_text: message to send
    - current_state: AI conversation state

    Payload expected:
    {
        "subscriber": {"id": "12345"},
        "custom_fields": {
            "ai_state": "STATE_4_OFFER",
            "last_product": "Сукня Анна"
        }
    }
    """
    # Verify token
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    if verify_token and verify_token != x_manychat_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    # Extract subscriber ID
    subscriber = payload.get("subscriber") or payload.get("user") or {}
    user_id = str(subscriber.get("id") or subscriber.get("user_id") or "unknown")

    if user_id == "unknown":
        return {
            "needs_followup": False,
            "reason": "unknown_user",
        }

    # Get custom fields from ManyChat
    custom_fields = payload.get("custom_fields") or {}
    current_state = custom_fields.get("ai_state", "STATE_0_INIT")
    last_product = custom_fields.get("last_product", "")

    # Generate follow-up based on state
    followup_text = _generate_followup_text(current_state, last_product)
    needs_followup = followup_text is not None

    # Build response for ManyChat Conditions
    return {
        "needs_followup": needs_followup,
        "followup_text": followup_text or "",
        "current_state": current_state,
        "set_field_values": [
            {"field_name": "followup_sent", "field_value": "true" if needs_followup else "false"},
        ],
        "add_tag": ["followup_sent"] if needs_followup else [],
    }


# ---------------------------------------------------------------------------
# CRM Order Creation Endpoint
# ---------------------------------------------------------------------------
@app.post("/webhooks/manychat/create-order")
async def manychat_create_order(
    payload: dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Create order in CRM from ManyChat data.

    IDEMPOTENT: Uses deterministic external_id based on user + product + price.
    Duplicate requests return existing order instead of creating new one.
    Uses CRMService and crm_orders table for proper persistence.

    Payload expected:
    {
        "subscriber": {"id": "12345"},
        "custom_fields": {
            "client_name": "Іванов Іван",
            "client_phone": "+380501234567",
            "client_city": "Київ",
            "client_nova_poshta": "25",
            "last_product": "Сукня Анна",
            "order_sum": "1200"
        }
    }
    """
    import hashlib

    from src.integrations.crm.crmservice import CRMService
    from src.services.orders import (
        build_missing_data_prompt,
        validate_order_data,
    )
    # PostgreSQL implementation

    # Verify token
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    if verify_token and verify_token != x_manychat_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    # Extract data
    subscriber = payload.get("subscriber") or payload.get("user") or {}
    user_id = str(subscriber.get("id") or subscriber.get("user_id") or "unknown")
    custom_fields = payload.get("custom_fields") or {}

    # Parse fields
    full_name = custom_fields.get("client_name")
    phone = custom_fields.get("client_phone")
    city = custom_fields.get("client_city")
    nova_poshta = custom_fields.get("client_nova_poshta")
    product_name = custom_fields.get("last_product", "Товар")
    order_sum = custom_fields.get("order_sum", "0")

    try:
        price = float(order_sum)
    except (ValueError, TypeError):
        price = 0.0

    # Validate data
    products = [{"product_id": 1, "name": product_name, "price": price}] if product_name else []
    validation = validate_order_data(full_name, phone, city, nova_poshta, products)

    if not validation.can_submit_to_crm:
        # Return prompt asking for missing data
        prompt = build_missing_data_prompt(validation)
        return {
            "success": False,
            "needs_data": True,
            "missing_fields": validation.missing_fields,
            "prompt": prompt,
            "set_field_values": [
                {"field_name": "order_status", "field_value": "needs_data"},
            ],
        }

    # === IDEMPOTENCY: Create deterministic external_id ===
    # Hash: user_id + product_name + price (normalized)
    idempotency_data = f"{user_id}|{product_name.lower().strip()}|{int(price * 100)}"
    idempotency_hash = hashlib.sha256(idempotency_data.encode()).hexdigest()[:16]
    external_id = f"mc_{user_id}_{idempotency_hash}"

    logger.info(
        "[CREATE_ORDER] Idempotency key: %s (user=%s, product=%s, price=%s)",
        external_id,
        user_id,
        product_name[:20],
        price,
    )

    # === CHECK FOR EXISTING ORDER IN crm_orders (PostgreSQL) ===
    import psycopg
    from src.services.storage import get_postgres_url
    
    try:
        postgres_url = get_postgres_url()
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, crm_order_id, status, task_id
                    FROM crm_orders
                    WHERE external_id = %s
                    LIMIT 1
                    """,
                    (external_id,),
                )
                existing = cur.fetchone()
        
        if existing:
            # existing is a tuple: (id, crm_order_id, status, task_id)
            order_id, crm_order_id, order_status, task_id = existing
            logger.info(
                "[CREATE_ORDER] Duplicate detected, returning existing order: %s",
                crm_order_id,
            )
            return {
                "success": True,
                "order_id": crm_order_id,
                "status": order_status,
                "task_id": task_id,
                "message": "Замовлення вже створено! 🎉",
                "duplicate": True,
                "set_field_values": [
                    {
                        "field_name": "order_status",
                        "field_value": order_status or "created",
                    },
                    {"field_name": "crm_external_id", "field_value": external_id},
                    {
                        "field_name": "crm_order_id",
                        "field_value": crm_order_id or "",
                    },
                ],
                "add_tag": ["order_created"]
                if order_status == "created"
                else ["order_queued"],
            }
    except Exception as e:
        logger.warning("[CREATE_ORDER] Failed to check for duplicate: %s", e)

    # Create order using CRMService
    try:
        # Initialize CRMService
        crm_service = CRMService()

        # Prepare order data
        order_data = {
            "customer": {
                "full_name": full_name,
                "phone": phone,
                "city": city,
                "nova_poshta_branch": nova_poshta,
                "manychat_id": user_id,
            },
            "items": [
                {
                    "product_id": 1,
                    "product_name": product_name,
                    "size": "",
                    "color": "",
                    "price": price,
                }
            ],
            "source": "manychat",
            "source_id": user_id,
        }

        # Create order with persistence
        result = await crm_service.create_order_with_persistence(
            session_id=user_id, external_id=external_id, order_data=order_data
        )

        if result.get("status") in ["queued", "created"]:
            logger.info(
                "[CREATE_ORDER] Order created successfully: %s",
                result.get("crm_order_id"),
            )

            return {
                "success": True,
                "order_id": result.get("crm_order_id"),
                "status": result.get("status"),
                "task_id": result.get("task_id"),
                "external_id": external_id,
                "message": "Замовлення успішно створено! 🎉",
                "set_field_values": [
                    {"field_name": "order_status", "field_value": result.get("status")},
                    {"field_name": "crm_external_id", "field_value": external_id},
                    {"field_name": "crm_order_id", "field_value": result.get("crm_order_id") or ""},
                    {"field_name": "crm_task_id", "field_value": result.get("task_id") or ""},
                ],
                "add_tag": ["order_created"]
                if result.get("status") == "created"
                else ["order_queued"],
            }
        else:
            logger.error(
                "[CREATE_ORDER] Order creation failed: %s",
                result.get("error"),
            )
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "message": "Не вдалося створити замовлення. Спробуйте ще раз.",
                "set_field_values": [
                    {"field_name": "order_status", "field_value": "failed"},
                ],
            }

    except Exception as e:
        logger.exception("[CREATE_ORDER] Failed to create order: %s", e)
        return {
            "success": False,
            "error": str(e),
            "message": "Сталася помилка при створенні замовлення",
            "set_field_values": [
                {"field_name": "order_status", "field_value": "error"},
            ],
        }


def _generate_followup_text(current_state: str, last_product: str = "") -> str | None:
    """Generate follow-up message based on conversation state.

    Returns None if no follow-up needed (e.g., order completed).
    """
    followup_templates = {
        "STATE_1_DISCOVERY": "Привіт! 🤍 Можливо, підказати щось з одягу для дитини?",
        "STATE_2_VISION": "Чи сподобалась модель? Можу показати інші кольори або розміри 🤍",
        "STATE_3_SIZE_COLOR": "Підказати з розміром? Напишіть зріст дитини — підберу найкращий варіант 📏",
        "STATE_4_OFFER": f"Ще раздумуєте над {last_product if last_product else 'замовленням'}? Можу щось уточнити? 🤍",
        "STATE_5_PAYMENT_DELIVERY": "Чекаю на дані для доставки: ПІБ, телефон, місто та відділення Нової Пошти 📦",
    }

    # No follow-up for these states
    no_followup_states = {
        "STATE_0_INIT",  # Not started yet
        "STATE_6_UPSELL",  # Already upselling
        "STATE_7_END",  # Order completed
        "STATE_8_COMPLAINT",  # Complaint handling
    }

    if current_state in no_followup_states:
        return None

    return followup_templates.get(current_state, "Чим можу допомогти? 🤍")
