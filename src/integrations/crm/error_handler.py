"""CRM Error Handler - Handles CRM operation failures, retries and escalations."""

from __future__ import annotations

import logging
from typing import Any

from src.services.core.observability import track_metric


logger = logging.getLogger(__name__)


class CRMErrorHandler:
    """CRM error handling service.
    
    Handles CRM operation failures by escalating to human operators.
    Note: Retry logic is handled by Celery tasks (see src/workers/tasks/crm.py),
    not by this handler. This handler only handles escalation.
    """

    async def escalate_to_operator(
        self,
        session_id: str,
        external_id: str,
        error_details: str,
    ) -> dict[str, Any]:
        """Escalate CRM failure to human operator.
        
        This method logs the escalation and tracks metrics.
        Actual operator notification is handled by external systems.
        
        Args:
            session_id: User session ID
            external_id: CRM external order ID
            error_details: Error description
            
        Returns:
            dict with escalation status and user-facing message
        """
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


def get_crm_error_handler() -> CRMErrorHandler:
    """Get CRM error handler singleton."""
    return CRMErrorHandler()
