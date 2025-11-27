"""ASGI app exposing Telegram and ManyChat webhooks.

This module uses proper FastAPI dependency injection and lifespan management
instead of global singletons.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from aiogram.types import Update
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.conf.config import settings
from src.core.logging import setup_logging
from src.integrations.manychat.webhook import ManychatPayloadError
from src.server.dependencies import (
    BotDep,
    DispatcherDep,
    ManychatHandlerDep,
    MessageStoreDep,
    get_bot,
    get_cached_dispatcher,
    get_cached_manychat_handler,
    get_message_store,
)
from src.server.middleware import setup_middleware
from src.services.followups import run_followups
from src.services.summarization import run_retention

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown events."""
    # Configure logging (JSON in production, pretty in development)
    is_production = settings.PUBLIC_BASE_URL != "http://localhost:8000"
    setup_logging(
        level="INFO",
        json_format=is_production,
        service_name="mirt-ai",
    )

    # Startup
    logger.info("Starting MIRT AI Webhooks server")

    # Register Telegram webhook if configured
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


app = FastAPI(
    title="MIRT AI Webhooks",
    description="AI-powered shopping assistant webhooks for Telegram and ManyChat",
    version="1.0.0",
    lifespan=lifespan,
)

# Setup middleware (rate limiting, request logging)
setup_middleware(app, enable_rate_limit=True, enable_logging=True)


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Health check endpoint with dependency status."""
    from src.services.supabase_client import get_supabase_client

    status = "ok"
    checks: Dict[str, str] = {}

    # Перевірка Supabase
    try:
        client = get_supabase_client()
        if client:
            # Простий ping запит
            client.table(settings.SUPABASE_TABLE).select("session_id").limit(1).execute()
            checks["supabase"] = "ok"
        else:
            checks["supabase"] = "disabled"
    except Exception as e:
        checks["supabase"] = f"error: {type(e).__name__}"
        status = "degraded"
        logger.warning("Health check: Supabase unavailable: %s", e)

    return {
        "status": status,
        "checks": checks,
        "version": "1.0.0",
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
    payload: Dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
) -> Dict[str, Any]:
    """Handle incoming ManyChat webhook payloads."""
    verify_token = settings.MANYCHAT_VERIFY_TOKEN
    if verify_token and verify_token != x_manychat_token:
        raise HTTPException(status_code=401, detail="Invalid ManyChat token")

    handler = get_cached_manychat_handler()
    try:
        return await handler.handle(payload)
    except ManychatPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/automation/mirt-summarize-prod-v1")
async def run_summarization(
    payload: Dict[str, Any],
    message_store: MessageStoreDep,
) -> Dict[str, Any]:
    """Summarize and prune old messages for a session.
    
    Called by ManyChat after 3 days of inactivity.
    Saves summary to mirt_users.summary and deletes messages from mirt_messages.
    
    Payload:
    {
        "user_id": 12345,
        "session_id": "12345",
        "action": "summarize"
    }
    """
    session_id = payload.get("session_id")
    user_id = payload.get("user_id")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # Convert user_id to int if provided
    user_id_int = int(user_id) if user_id else None
    
    summary = run_retention(session_id, message_store, user_id=user_id_int)
    
    return {
        "session_id": session_id,
        "user_id": user_id,
        "summary": summary,
        "action": "remove_tags",  # Signal to ManyChat to remove humanNeeded-wd tag
        "status": "ok",
    }


@app.post("/automation/mirt-followups-prod-v1")
async def trigger_followups(
    payload: Dict[str, Any],
    message_store: MessageStoreDep,
) -> Dict[str, Any]:
    """Trigger follow-up messages for inactive sessions."""
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    schedule_hours = payload.get("schedule_hours")
    if schedule_hours is not None and not isinstance(schedule_hours, list):
        raise HTTPException(status_code=400, detail="schedule_hours must be a list of integers")

    followup = run_followups(session_id, message_store, schedule_hours=schedule_hours)
    return {
        "session_id": session_id,
        "followup_created": bool(followup),
        "content": followup.content if followup else None,
        "tags": followup.tags if followup else [],
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# ManyChat Follow-up Endpoint
# ---------------------------------------------------------------------------
@app.post("/webhooks/manychat/followup")
async def manychat_followup(
    payload: Dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
    message_store: MessageStoreDep = None,
) -> Dict[str, Any]:
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
    payload: Dict[str, Any],
    x_manychat_token: str | None = Header(default=None),
) -> Dict[str, Any]:
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
    from src.services.order_model import (
        Order, OrderItem, CustomerInfo, PaymentMethod,
        validate_order_data, build_missing_data_prompt,
    )
    from src.integrations.crm.snitkix import get_snitkix_client
    
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
        "STATE_2_VISION": f"Чи сподобалась модель? Можу показати інші кольори або розміри 🤍",
        "STATE_3_SIZE_COLOR": "Підказати з розміром? Напишіть зріст дитини — підберу найкращий варіант 📏",
        "STATE_4_OFFER": f"Ще раздумуєте над {last_product if last_product else 'замовленням'}? Можу щось уточнити? 🤍",
        "STATE_5_PAYMENT_DELIVERY": "Чекаю на дані для доставки: ПІБ, телефон, місто та відділення Нової Пошти 📦",
    }
    
    # No follow-up for these states
    no_followup_states = {
        "STATE_0_INIT",      # Not started yet
        "STATE_6_UPSELL",    # Already upselling
        "STATE_7_END",       # Order completed
        "STATE_8_COMPLAINT", # Complaint handling
    }
    
    if current_state in no_followup_states:
        return None
    
    return followup_templates.get(current_state, "Чим можу допомогти? 🤍")
