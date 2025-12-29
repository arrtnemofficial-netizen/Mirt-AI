"""ASGI app exposing Telegram and ManyChat webhooks.

This module uses proper FastAPI dependency injection and lifespan management
instead of global singletons.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from src.conf.config import settings
from src.core.logging import setup_logging
from src.server.middleware import setup_middleware


logger = logging.getLogger(__name__)


# Helper functions moved to src/server/routers/common.py
# Models moved to src/server/routers/schemas.py


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

    from src.server.routers.common import get_build_info

    build_info = get_build_info()
    logger.info(
        "Build info: git_sha=%s build_id=%s",
        build_info.get("git_sha"),
        build_info.get("build_id"),
    )

    # Log LLM configuration (critical for production verification)
    logger.info("LLM Configuration:")
    logger.info("  Provider: %s", settings.LLM_PROVIDER)
    logger.info("  Model: %s", settings.AI_MODEL)
    logger.info("  Active Model: %s", settings.active_llm_model)
    logger.info("  Temperature: %s", settings.LLM_TEMPERATURE)
    logger.info("  Max Tokens: %s", settings.LLM_MAX_TOKENS)

    # Log Observability status
    logger.info("Observability: %s", "ENABLED" if settings.ENABLE_OBSERVABILITY else "DISABLED")
    if settings.ENABLE_OBSERVABILITY:
        logger.info("  llm_traces table will be populated")
    else:
        logger.warning("  llm_traces table will NOT be populated (ENABLE_OBSERVABILITY=False)")

    # Log Memory system status
    try:
        from src.services.memory import MemoryService
        memory_service = MemoryService()
        if memory_service.enabled:
            logger.info("Memory System: ENABLED")
            logger.info("  mirt_profiles and mirt_memories will be populated")
        else:
            logger.warning("Memory System: DISABLED (DATABASE_URL not configured)")
    except Exception as e:
        logger.warning("Memory System: Check failed - %s", e)

    # Log Celery status
    if settings.CELERY_ENABLED:
        logger.info("Celery: ENABLED")
        logger.info("  Worker: %s", "Running" if settings.CELERY_ENABLED else "Not configured")
        logger.info("  Beat: Scheduled tasks enabled")
    else:
        logger.warning("Celery: DISABLED - scheduled tasks will NOT run")

    # Check external services (non-blocking, with timeouts)
    logger.info("Checking external services...")

    async def check_http_reachable(name: str, url: str, timeout: float = 3.0) -> tuple[bool, int | None, str | None]:
        """Check if HTTP service is reachable.
        
        Uses HEAD first (lighter), falls back to GET if HEAD returns 405 Method Not Allowed.
        Treats 200-399 as reachable (handles redirects properly).
        
        Returns: (is_reachable, status_code, error_type)
        - is_reachable: True if status 200-399
        - status_code: HTTP status code if request succeeded
        - error_type: Exception type name if request failed
        """
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                # Try HEAD first (lighter, no body)
                try:
                    response = await client.head(url)
                    status = response.status_code
                except httpx.HTTPStatusError as e:
                    # If HEAD returns 405 Method Not Allowed, fallback to GET
                    if e.response.status_code == 405:
                        response = await client.get(url)
                        status = response.status_code
                    else:
                        # Other HTTP errors - still return status code
                        status = e.response.status_code
                        is_reachable = 200 <= status < 400
                        return is_reachable, status, None
                except Exception:
                    # If HEAD fails for other reasons (network, timeout), try GET
                    response = await client.get(url)
                    status = response.status_code

                is_reachable = 200 <= status < 400
                return is_reachable, status, None
        except Exception as e:
            return False, None, type(e).__name__

    # Check ManyChat API
    if settings.MANYCHAT_API_KEY:
        reachable, status, err = await check_http_reachable("ManyChat API", settings.MANYCHAT_API_URL, timeout=5.0)
        if reachable:
            logger.info("✓ ManyChat API: Reachable (status=%d)", status)
        else:
            logger.warning("⚠ ManyChat API: %s (status=%s, err=%s)",
                          "Unreachable" if err else "Not reachable", status, err)
    else:
        logger.warning("⚠ ManyChat API: Not configured (MANYCHAT_API_KEY not set)")

    # Check Sitniks CRM
    if settings.SNITKIX_API_KEY and settings.ENABLE_CRM_INTEGRATION:
        reachable, status, err = await check_http_reachable("Sitniks CRM", settings.SNITKIX_API_URL, timeout=5.0)
        if reachable:
            logger.info("✓ Sitniks CRM: Reachable (status=%d)", status)
        else:
            logger.warning("⚠ Sitniks CRM: %s (status=%s, err=%s)",
                          "Unreachable" if err else "Not reachable", status, err)
    elif settings.ENABLE_CRM_INTEGRATION:
        logger.warning("⚠ Sitniks CRM: Not configured (SNITKIX_API_KEY not set but ENABLE_CRM_INTEGRATION=true)")
    else:
        logger.info("Sitniks CRM: Integration disabled")

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

# Setup middleware (rate limiting, request logging)
setup_middleware(app, enable_rate_limit=True, enable_logging=True)

# Include routers
from src.server.routers import (
    api_v1,
    automation,
    health,
    media,
    webhooks_manychat,
)


app.include_router(media.router, tags=["media"])
app.include_router(health.router, tags=["health"])
app.include_router(api_v1.router, tags=["api"])
app.include_router(webhooks_manychat.router, tags=["webhooks"])
app.include_router(automation.router, tags=["automation"])


# Models and helpers moved to src/server/routers/schemas.py and routers/common.py
# All endpoints moved to routers - see include_router calls above

# Telegram webhook removed - Telegram is used ONLY for manager notifications (outgoing via NotificationService)
# No incoming webhook needed for manager notifications
