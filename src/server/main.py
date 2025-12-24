"""ASGI app exposing Telegram and ManyChat webhooks.

This module is now a thin orchestrator that:
1. Manages FastAPI app lifecycle
2. Includes routers for all endpoints
3. Sets up middleware

All endpoint logic has been extracted to src/server/routers/ for maintainability.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from src.conf.config import settings, validate_required_settings
from src.core.logging import setup_logging
from src.server.dependencies import get_bot
from src.server.exceptions import APIError
from src.server.middleware import setup_middleware
from src.server.routers import (
    automation_router,
    health_router,
    manychat_router,
    media_router,
    sitniks_router,
    snitkix_router,
    telegram_router,
)


logger = logging.getLogger(__name__)


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
    # ==========================================================================
    # PRE-FLIGHT VALIDATION: Check configuration format BEFORE any connections
    # ==========================================================================
    try:
        from src.server.preflight_validation import validate_and_raise_on_errors
        
        logger.info("Running pre-flight configuration validation...")
        await validate_and_raise_on_errors()
        logger.info("Pre-flight configuration validation passed")
    except Exception as e:
        logger.critical("Pre-flight configuration validation failed: %s", e)
        raise
    
    # Validate required settings (legacy, but keep for backward compatibility)
    try:
        validate_required_settings()
    except RuntimeError as e:
        logger.critical("Configuration validation failed: %s", e)
        raise

    # Initialize Sentry first
    _init_sentry()

    # Initialize OpenTelemetry tracing
    try:
        from src.services.core.observability import setup_opentelemetry_tracing

        if setup_opentelemetry_tracing():
            logger.info("OpenTelemetry distributed tracing enabled")
        else:
            logger.debug("OpenTelemetry tracing not available (optional dependency)")
    except Exception as e:
        logger.warning("Failed to initialize OpenTelemetry tracing: %s", e)

    # Configure logging (JSON in production, pretty in development)
    is_production = settings.PUBLIC_BASE_URL != "http://localhost:8000"
    setup_logging(
        level="INFO",
        json_format=is_production,
        service_name="mirt-ai",
    )

    # Startup
    logger.info("Starting MIRT AI Webhooks server")

    # ==========================================================================
    # WARMUP: Pre-initialize the graph to avoid 20+ second delay on first request
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

    # ==========================================================================
    # CRITICAL COMPONENTS VALIDATION (Fail-Fast)
    # ==========================================================================
    try:
        from src.core.errors import ServiceError
        from src.server.startup_validation import validate_critical_components
        
        logger.info("Validating critical components...")
        critical_checks = await validate_critical_components()
        
        if not critical_checks["all_ready"]:
            failures = critical_checks["failures"]
            errors = critical_checks.get("errors", [])
            
            # Log structured errors with recommendations
            for error in errors:
                logger.critical(
                    "[VALIDATION] %s [%s]: %s",
                    error.get("component", "unknown"),
                    error.get("error_code", "UNKNOWN"),
                    error.get("message", "Unknown error")
                )
                logger.critical(
                    "[VALIDATION] Recommendations:\n%s",
                    "\n".join(f"  - {r}" for r in error.get("recommendations", []))
                )
            
            error_msg = f"Startup validation failed. Critical components not ready: {', '.join(failures)}"
            logger.critical(error_msg)
            logger.critical("Validation details: %s", critical_checks["checks"])
            raise RuntimeError(error_msg)
        
        logger.info("All critical components validated successfully")
    except ServiceError as e:
        # Structured error from validation - log and re-raise
        logger.critical(
            "[VALIDATION] %s [%s]: %s",
            e.component, e.error_code, e.message
        )
        logger.critical(
            "[VALIDATION] Recommendations:\n%s",
            "\n".join(f"  - {r}" for r in e.recommendations)
        )
        raise RuntimeError(f"Startup validation failed: {e.message}") from e
    except RuntimeError:
        # Re-raise RuntimeError from validation (fail-fast)
        raise
    except Exception as e:
        logger.critical("Startup validation error: %s", e)
        raise RuntimeError(f"Startup validation failed: {str(e)}") from e

    # Telegram webhook: \u0440\u0435\u0454\u0441\u0442\u0440\u0443\u0454\u043c\u043e, \u044f\u043a\u0449\u043e \u0454 token \u0456 \u043f\u0443\u0431\u043b\u0456\u0447\u043d\u0430 \u0430\u0434\u0440\u0435\u0441\u0430
    base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()

    if base_url and token and base_url != "http://localhost:8000":
        try:
            bot = get_bot()
            full_url = f"{base_url}{settings.TELEGRAM_WEBHOOK_PATH}"
            await bot.set_webhook(full_url)
            logger.info("Telegram webhook registered: %s", full_url)
        except Exception as e:
            logger.error("Failed to register Telegram webhook: %s", e)

    # ==========================================================================
    # RUNTIME HEALTH MONITORING
    # ==========================================================================
    try:
        from src.server.health_monitor import start_health_monitoring
        
        # Start health monitoring in background (runs during app lifetime)
        await start_health_monitoring(check_interval=60.0)
        logger.info("Runtime health monitoring started")
    except Exception as e:
        logger.warning("Failed to start health monitoring: %s", e)

    yield

    # Shutdown
    logger.info("Shutting down MIRT AI Webhooks server")
    
    # Stop health monitoring
    try:
        from src.server.health_monitor import stop_health_monitoring
        await stop_health_monitoring()
    except Exception as e:
        logger.warning("Failed to stop health monitoring: %s", e)
    
    # Gracefully close checkpointer pool
    try:
        from src.agents.langgraph.checkpointer import shutdown_checkpointer_pool
        await shutdown_checkpointer_pool()
    except Exception as e:
        logger.warning("Failed to shutdown checkpointer pool: %s", e)


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="MIRT AI Webhooks",
    description="AI-powered shopping assistant webhooks for Telegram and ManyChat",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handle custom API exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail or exc.message,
            "error": exc.message,
        },
        headers={"Retry-After": str(exc.retry_after)} if hasattr(exc, "retry_after") and exc.retry_after else None,
    )


# Setup middleware (rate limiting, request logging)
setup_middleware(app, enable_rate_limit=True, enable_logging=True)

# =============================================================================
# Include Routers
# =============================================================================

app.include_router(health_router)
app.include_router(telegram_router)
app.include_router(media_router)
app.include_router(manychat_router)
app.include_router(snitkix_router)
app.include_router(sitniks_router)
app.include_router(automation_router)
