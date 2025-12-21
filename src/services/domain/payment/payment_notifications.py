"""
Payment Notifications Service.
==============================
Handles Telegram alerts for orders and critical payment errors.
"""

from __future__ import annotations

import logging

from src.services.domain.payment.payment_config import get_payment_section
from src.services.infra.notification_service import NotificationService

logger = logging.getLogger(__name__)


async def notify_order_success(session_id: str, total: float, products: list[str]):
    """Send success alert to managers."""
    try:
        notifications = get_payment_section("notifications")
        order_context = get_payment_section("order_context")
        template = notifications.get("order_success")
        if isinstance(template, str) and template:
            msg = template.format(
                session_id=session_id,
                total=total,
                currency=order_context.get("currency", "UAH"),
                products=", ".join(products),
            )
        else:
            msg = (
                "NEW ORDER\n"
                f"Session: {session_id}\n"
                f"Total: {total} UAH\n"
                f"Products: {', '.join(products)}"
            )
        await NotificationService.notify_manager("new_order", msg)
    except Exception as e:
        logger.error("Failed to send order success alert: %s", e)


async def notify_payment_critical_error(session_id: str, error: str):
    """Send critical error alert to managers."""
    try:
        notifications = get_payment_section("notifications")
        template = notifications.get("critical_error")
        if isinstance(template, str) and template:
            msg = template.format(session_id=session_id, error=error)
        else:
            msg = f"CRITICAL ERROR\nSession: {session_id}\nError: {error}"
        await NotificationService.notify_manager("new_order", msg)
    except Exception as e:
        logger.error("Failed to send critical error alert: %s", e)
