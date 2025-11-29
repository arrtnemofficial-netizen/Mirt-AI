"""ManyChat integration package.

Provides:
- ManychatWebhook: Webhook handler for ManyChat requests
- ManyChatClient: API client for managing tags and custom fields
"""

from src.integrations.manychat.api_client import (
    ManyChatAPIError,
    ManyChatClient,
    get_manychat_client,
    remove_ai_tag_from_subscriber,
    update_subscriber_summary_fields,
)
from src.integrations.manychat.webhook import ManychatPayloadError, ManychatWebhook


__all__ = [
    "ManychatWebhook",
    "ManychatPayloadError",
    "ManyChatClient",
    "ManyChatAPIError",
    "get_manychat_client",
    "remove_ai_tag_from_subscriber",
    "update_subscriber_summary_fields",
]
