"""ManyChat integration package.

Provides:
- ManychatWebhook: Webhook handler for ManyChat requests (sync response mode)
- ManyChatAsyncService: Async push-based service (recommended)
- ManyChatPushClient: Low-level API client for pushing messages
- ManyChatClient: API client for managing tags and custom fields
"""

from src.integrations.manychat.api_client import (
    ManyChatAPIError,
    ManyChatClient,
    get_manychat_client,
    remove_ai_tag_from_subscriber,
    update_subscriber_summary_fields,
)
from src.integrations.manychat.async_service import (
    ManyChatAsyncService,
    get_manychat_async_service,
)
from src.integrations.manychat.push_client import (
    ManyChatPushClient,
    get_manychat_push_client,
)
from src.integrations.manychat.webhook import ManychatPayloadError, ManychatWebhook


__all__ = [
    # Webhook handlers
    "ManychatWebhook",
    "ManychatPayloadError",
    # Async push service (recommended)
    "ManyChatAsyncService",
    "get_manychat_async_service",
    # Push client
    "ManyChatPushClient",
    "get_manychat_push_client",
    # API client
    "ManyChatClient",
    "ManyChatAPIError",
    "get_manychat_client",
    "remove_ai_tag_from_subscriber",
    "update_subscriber_summary_fields",
]
