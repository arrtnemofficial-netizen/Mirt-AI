"""CRM Error Handler - Handles CRM operation failures, retries and escalations."""

from __future__ import annotations

import logging
from typing import Any

from src.services.core.observability import track_metric


logger = logging.getLogger(__name__)


class CRMErrorHandler:
    """Stub for CRM error handling logic."""

    async def escalate_to_operator(
        self,
        session_id: str,
        external_id: str,
        error_details: str,
    ) -> dict[str, Any]:
        """Escalate CRM failure to human operator."""
        logger.warning(
            "[CRM:ERROR] Escalating session %s (ext_id: %s) due to: %s",
            session_id,
            external_id,
            error_details,
        )
        track_metric("crm_error_escalated", 1, {"session_id": session_id})
        
        return {
            "status": "escalated",
            "message": "Оператор сповіщений про проблему з вашим замовленням і скоро зв'яжеться з вами.",
        }

    async def retry_crm_order_in_state(
        self,
        session_id: str,
        external_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Attempt to retry CRM order creation."""
        retry_count = state.get("crm_retry_count", 0) + 1
        logger.info(
            "[CRM:ERROR] Retrying session %s (ext_id: %s), attempt %d",
            session_id,
            external_id,
            retry_count,
        )
        track_metric("crm_error_retry", 1, {"session_id": session_id})

        # Logic for actual retry would go here
        # For now, we return success and expect caller to handle the loop
        return {
            "status": "retrying",
            "retry_count": retry_count,
            "message": f"Пробую ще раз оформити ваше замовлення (спроба {retry_count})...",
        }


def get_crm_error_handler() -> CRMErrorHandler:
    """Get CRM error handler singleton."""
    return CRMErrorHandler()
