"""CRM integrations package.

Only Sitniks chat status service is available (no orders/webhooks).
"""

from src.integrations.crm.sitniks_chat_service import (
    SitniksChatService,
    get_sitniks_chat_service,
)


__all__ = ["SitniksChatService", "get_sitniks_chat_service"]
