"""ASGI app exposing Telegram and ManyChat webhooks.

This module is now a thin orchestrator that:
1. Manages FastAPI app lifecycle
2. Includes routers for all endpoints
3. Sets up middleware

All endpoint logic has been extracted to src/server/routers/ for maintainability.
"""

from __future__ import annotations

import logging
<<<<<<< Updated upstream
from contextlib import asynccontextmanager
from typing import Any

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.conf.config import settings
from src.core.logging import setup_logging
from src.integrations.manychat.webhook import ManychatPayloadError
from src.server.dependencies import (
    MessageStoreDep,
    get_bot,
    get_cached_dispatcher,
    get_cached_manychat_handler,
)
from src.server.middleware import setup_middleware
=======
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.conf.config import settings
from src.core.logging import setup_logging
from src.server.dependencies import get_bot
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
>>>>>>> Stashed changes


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
    # Initialize Sentry first
    _init_sentry()

    # Configure logging (JSON in production, pretty in development)
    is_production = settings.PUBLIC_BASE_URL != "http://localhost:8000"
    setup_logging(
        level="INFO",
        json_format=is_production,
        service_name="mirt-ai",
    )

    # Startup
    logger.info("Starting MIRT AI Webhooks server")

<<<<<<< Updated upstream
    # Register Telegram webhook if configured
=======
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

    # Telegram webhook: реєструємо, якщо є token і публічна адреса
>>>>>>> Stashed changes
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

    yield

    # Shutdown
    logger.info("Shutting down MIRT AI Webhooks server")


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="MIRT AI Webhooks",
    description="AI-powered shopping assistant webhooks for Telegram and ManyChat",
    version="1.0.0",
    lifespan=lifespan,
)

# Setup middleware (rate limiting, request logging)
setup_middleware(app, enable_rate_limit=True, enable_logging=True)

<<<<<<< Updated upstream

@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint with dependency status."""
    from src.services.supabase_client import get_supabase_client

    status = "ok"
    checks: dict[str, Any] = {}

    # Перевірка Supabase
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
        from src.services.llm_fallback import get_llm_service
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
        "version": "1.0.0",
        "celery_enabled": settings.CELERY_ENABLED,
        "llm_provider": settings.LLM_PROVIDER,
        "active_model": settings.active_llm_model,
    }


@app.post(settings.TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> JSONResponse:
    """Handle incoming Telegram webhook updates."""
    bot = get_bot()
    dp = get_cached_dispatcher()

    body = await request.json()
    update = Update.model_validate(body)
    await dp.feed_update(bot=bot, update=update)
    return JSONResponse({"ok": True})


@app.post("/webhooks/manychat")
async def manychat_webhook(
    payload: dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Handle incoming ManyChat webhook payloads."""
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    if verify_token and verify_token != x_manychat_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    handler = get_cached_manychat_handler()
    try:
        return await handler.handle(payload)
    except ManychatPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/automation/mirt-summarize-prod-v1")
async def run_summarization(
    payload: dict[str, Any],
    message_store: MessageStoreDep,
) -> dict[str, Any]:
    """Summarize and prune old messages for a session.

    Called by ManyChat after 3 days of inactivity.
    Saves summary to mirt_users.summary and deletes messages from mirt_messages.

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

    This endpoint is called when all customer data is collected
    and order should be created in Snitkix CRM.

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
    from src.integrations.crm.snitkix import get_snitkix_client
    from src.services.order_model import (
        CustomerInfo,
        Order,
        OrderItem,
        build_missing_data_prompt,
        validate_order_data,
    )

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

    # Create order
    try:
        order = Order(
            external_id=f"mc_{user_id}",
            customer=CustomerInfo(
                full_name=full_name,
                phone=phone,
                city=city,
                nova_poshta_branch=nova_poshta,
                manychat_id=user_id,
            ),
            items=[
                OrderItem(
                    product_id=1,
                    product_name=product_name,
                    size="",
                    color="",
                    price=price,
                ),
            ],
            source="manychat",
            source_id=user_id,
        )

        # Send to CRM
        crm = get_snitkix_client()
        response = await crm.create_order(order)

        if response.success:
            return {
                "success": True,
                "order_id": response.order_id,
                "message": "Замовлення створено! 🎉",
                "set_field_values": [
                    {"field_name": "order_status", "field_value": "created"},
                    {"field_name": "crm_order_id", "field_value": response.order_id or ""},
                ],
                "add_tag": ["order_created"],
            }
        else:
            logger.error("CRM order creation failed: %s", response.error)
            return {
                "success": False,
                "error": response.error,
                "set_field_values": [
                    {"field_name": "order_status", "field_value": "crm_error"},
                ],
            }

    except Exception as e:
        logger.exception("Order creation error: %s", e)
        return {
            "success": False,
            "error": str(e),
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
=======
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
>>>>>>> Stashed changes
