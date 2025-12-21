"""
Payment Notifications Service.
==============================
Handles Telegram alerts for orders and critical payment errors.
"""

from __future__ import annotations

import logging
from src.services.infra.notification_service import NotificationService
from src.core.prompt_registry import get_snippet_by_header

logger = logging.getLogger(__name__)


async def notify_order_success(session_id: str, total: float, products: list[str]):
    """Send success alert to managers."""
    try:
        msg = f"✅ **НОВЕ ЗАМОВЛЕННЯ**\nСесія: `{session_id}`\nСума: {total} грн\nТовари: {', '.join(products)}"
        await NotificationService.notify_manager("new_order", msg)
    except Exception as e:
        logger.error("Failed to send order success alert: %s", e)


async def notify_payment_critical_error(session_id: str, error: str):
    """Send critical error alert to managers."""
    try:
        alert_tmpl = get_snippet_by_header("ADMIN_CRITICAL_ERROR")
        if alert_tmpl:
            msg = alert_tmpl[0].format(session_id=session_id, error=error)
            await NotificationService.notify_manager("new_order", msg)
        else:
            # Fallback
            msg = f"🚨 **CRITICAL ERROR**\nSession: `{session_id}`\nPayment Flow Failed!\nError: {error}"
            await NotificationService.notify_manager("new_order", msg)
    except Exception as e:
        logger.error("Failed to send critical error alert: %s", e)
