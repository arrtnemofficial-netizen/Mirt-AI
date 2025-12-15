"""CRM Error Handler and Retry UI.

Handles CRM operation failures and provides user-friendly retry options.
Integrates with LangGraph validation node for error recovery.

Features:
- Automatic retry for transient failures
- User-friendly error messages
- Manual retry prompts in chat
- Fallback to operator assistance
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from src.integrations.crm.crmservice import get_crm_service


logger = logging.getLogger(__name__)


class CRMErrorHandler:
    """Handles CRM errors and provides recovery options."""

    def __init__(self):
        self.crm_service = get_crm_service()
        self.retry_messages = {
            "network_error": "⚠️ Проблеми з зв'язком з CRM системою. Спробувати ще раз?",
            "crm_rejected": "📋 Замовлення не прийнято CRM. Перевірити дані та повторити?",
            "timeout": "⏰ CRM не відповідає. Спробувати ще раз чи передати оператору?",
            "rate_limit": "🚦 Забагато запитів до CRM. Спробувати через хвилину?",
            "unknown": "❌ Помилка CRM. Спробувати ще раз чи звернутись до оператора?",
        }

    def categorize_error(self, error: str, error_code: str | None = None) -> str:
        """Categorize CRM error for appropriate handling."""
        error_lower = error.lower()

        if any(keyword in error_lower for keyword in ["network", "connection", "timeout"]):
            return "network_error"
        elif error_code == "CRM_REJECTED" or "rejected" in error_lower:
            return "crm_rejected"
        elif "timeout" in error_lower:
            return "timeout"
        elif "rate limit" in error_lower or "too many" in error_lower:
            return "rate_limit"
        else:
            return "unknown"

    async def handle_crm_failure(
        self,
        session_id: str,
        external_id: str,
        error: str,
        error_code: str | None = None,
        retry_count: int = 0,
    ) -> dict[str, Any]:
        """Handle CRM operation failure and determine recovery strategy.
        
        Returns:
            dict with error handling strategy and user message
        """
        error_category = self.categorize_error(error, error_code)

        logger.warning(
            "[CRM:ERROR] Handling CRM failure session=%s external_id=%s category=%s retry=%d: %s",
            session_id,
            external_id,
            error_category,
            retry_count,
            error,
        )

        # Get failed order details
        failed_order = await self.crm_service.get_order_status(external_id=external_id)

        # Determine recovery strategy
        if retry_count >= 3:
            # Too many retries - escalate to operator
            return {
                "strategy": "escalate",
                "message": self._get_escalation_message(error_category),
                "external_id": external_id,
                "retry_count": retry_count,
                "can_retry": False,
                "order_data": failed_order,
            }

        if error_category in ["network_error", "timeout", "rate_limit"]:
            # Transient errors - can retry
            return {
                "strategy": "retry",
                "message": self._get_retry_message(error_category, retry_count),
                "external_id": external_id,
                "retry_count": retry_count,
                "can_retry": True,
                "order_data": failed_order,
            }
        elif error_category == "crm_rejected":
            # Business logic error - needs user intervention
            return {
                "strategy": "user_action",
                "message": self._get_user_action_message(error, failed_order),
                "external_id": external_id,
                "retry_count": retry_count,
                "can_retry": True,
                "order_data": failed_order,
            }
        else:
            # Unknown error - offer retry or escalation
            return {
                "strategy": "choice",
                "message": self._get_choice_message(error, retry_count),
                "external_id": external_id,
                "retry_count": retry_count,
                "can_retry": True,
                "order_data": failed_order,
            }

    async def retry_crm_order(
        self,
        session_id: str,
        external_id: str,
    ) -> dict[str, Any]:
        """Retry failed CRM order creation."""
        logger.info(
            "[CRM:ERROR] Retrying CRM order session=%s external_id=%s",
            session_id,
            external_id,
        )

        try:
            # Get failed order data
            failed_order = await self.crm_service.get_order_status(external_id=external_id)
            if not failed_order or not failed_order.get("order_data"):
                return {
                    "success": False,
                    "error": "Original order data not found",
                    "message": "❌ Не вдалося знайти дані замовлення для повторної спроби",
                }

            # Create new order with same data but new external_id
            order_data = failed_order["order_data"]
            new_external_id = f"{session_id}_retry_{int(datetime.now(UTC).timestamp())}"

            result = await self.crm_service.create_order_with_persistence(
                session_id=session_id,
                order_data=order_data,
                external_id=new_external_id,
            )

            if result.get("status") in ["queued", "created"]:
                return {
                    "success": True,
                    "message": "✅ Замовлення успішно відправлено до CRM",
                    "new_external_id": new_external_id,
                    "task_id": result.get("task_id"),
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                    "message": f"❌ Помилка при повторній спробі: {result.get('error', 'Невідома помилка')}",
                }

        except Exception as e:
            logger.exception(
                "[CRM:ERROR] Failed to retry CRM order session=%s external_id=%s: %s",
                session_id,
                external_id,
                e,
            )
            return {
                "success": False,
                "error": str(e),
                "message": f"❌ Критична помилка при повторній спробі: {e!s}",
            }

    async def escalate_to_operator(
        self,
        session_id: str,
        external_id: str,
        error_details: str,
    ) -> dict[str, Any]:
        """Escalate failed order to human operator."""
        logger.warning(
            "[CRM:ERROR] Escalating to operator session=%s external_id=%s",
            session_id,
            external_id,
        )

        try:
            # Update order status to escalated
            await self.crm_service.handle_webhook_status_update(
                crm_order_id=external_id,  # Use external_id since CRM order wasn't created
                new_status="escalated",
                metadata={
                    "escalated_at": datetime.now(UTC).isoformat(),
                    "error_details": error_details,
                    "session_id": session_id,
                },
            )

            # TODO: Send notification to operator (email, Slack, etc.)
            # await self.notification_service.notify_operator(session_id, external_id, error_details)

            return {
                "success": True,
                "message": "📞 Замовлення передано оператору. Ми зв'яжемося з вами найближчим часом.",
                "escalated": True,
            }

        except Exception as e:
            logger.exception(
                "[CRM:ERROR] Failed to escalate to operator session=%s external_id=%s: %s",
                session_id,
                external_id,
                e,
            )
            return {
                "success": False,
                "error": str(e),
                "message": f"❌ Не вдалося передати замовлення оператору: {e!s}",
            }

    def _get_retry_message(self, error_category: str, retry_count: int) -> str:
        """Get user-friendly retry message."""
        base_message = self.retry_messages.get(error_category, self.retry_messages["unknown"])

        if retry_count > 0:
            base_message = f"{base_message} (спроба {retry_count + 1}/3)"

        return base_message

    def _get_user_action_message(self, error: str, order_data: dict[str, Any] | None) -> str:
        """Get message for user action required errors."""
        message = "📋 Потрібна ваша увага:\n\n"

        if "missing" in error.lower():
            message += "• Відсутні обов'язкові дані\n"
        elif "invalid" in error.lower():
            message += "• Невірні дані у замовленні\n"
        else:
            message += f"• Помилка: {error}\n"

        message += "\nБудь ласка, перевірте:\n"
        message += "• ПІБ та номер телефону\n"
        message += "• Місто та відділення Нової пошти\n"
        message += "• Дані товару (розмір, колір)\n\n"
        message += "Готові повторити спробу? 🔄"

        return message

    def _get_choice_message(self, error: str, retry_count: int) -> str:
        """Get message offering choice between retry and escalation."""
        message = f"❌ Сталася помилка CRM: {error}\n\n"

        if retry_count > 0:
            message += f"(спроба {retry_count + 1}/3)\n\n"

        message += "Варіанти:\n"
        message += "1️⃣ Спробувати ще раз\n"
        message += "2️⃣ Передати оператору\n\n"
        message += "Що обираєте?"

        return message

    def _get_escalation_message(self, error_category: str) -> str:
        """Get message for escalation to operator."""
        base_message = "📞 Замовлення передано оператору через технічні проблеми.\n\n"

        if error_category == "network_error":
            base_message += "Причина: проблеми з зв'язком"
        elif error_category == "timeout":
            base_message += "Причина: CRM система не відповідає"
        elif error_category == "crm_rejected":
            base_message += "Причина: CRM система не прийняла замовлення"
        else:
            base_message += "Причина: технічна помилка"

        base_message += "\n\nМи зв'яжемося з вами найближчим часом для оформлення замовлення. 🕐"

        return base_message


# Global error handler instance
_error_handler: CRMErrorHandler | None = None


def get_crm_error_handler() -> CRMErrorHandler:
    """Get global CRM error handler instance."""
    global _error_handler
    if _error_handler is None:
        _error_handler = CRMErrorHandler()
    return _error_handler


# Integration functions for LangGraph

async def handle_crm_error_in_state(
    state: dict[str, Any],
    error: str,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Handle CRM error within LangGraph state."""
    session_id = state.get("session_id", "")
    external_id = state.get("crm_external_id", "")
    retry_count = state.get("crm_retry_count", 0)

    error_handler = get_crm_error_handler()
    result = await error_handler.handle_crm_failure(
        session_id=session_id,
        external_id=external_id,
        error=error,
        error_code=error_code,
        retry_count=retry_count,
    )

    return {
        "crm_error_result": result,
        "crm_retry_count": retry_count + 1,
        "dialog_phase": "CRM_ERROR_HANDLING",
        "awaiting_user_choice": result.get("can_retry", False),
    }


async def retry_crm_order_in_state(
    state: dict[str, Any],
) -> dict[str, Any]:
    """Retry CRM order from LangGraph state."""
    session_id = state.get("session_id", "")
    external_id = state.get("crm_external_id", "")

    error_handler = get_crm_error_handler()
    result = await error_handler.retry_crm_order(session_id, external_id)

    if result.get("success"):
        return {
            "crm_retry_result": result,
            "dialog_phase": "ORDER_CONFIRMED",
            "awaiting_user_choice": False,
        }
    else:
        return {
            "crm_retry_result": result,
            "dialog_phase": "CRM_ERROR_HANDLING",
            "awaiting_user_choice": True,
        }
