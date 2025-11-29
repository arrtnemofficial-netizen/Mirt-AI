"""ManyChat API client for subscriber management.

This module provides methods to:
- Add/remove tags from subscribers
- Update custom fields
- Send messages via API

Documentation: https://api.manychat.com/docs
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.conf.config import settings


logger = logging.getLogger(__name__)

# ManyChat API endpoints
MANYCHAT_API_BASE = "https://api.manychat.com/fb"


class ManyChatAPIError(Exception):
    """Raised when ManyChat API call fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ManyChatClient:
    """Client for ManyChat API operations."""

    def __init__(self, api_key: str | None = None):
        """Initialize ManyChat API client.

        Args:
            api_key: ManyChat API key. If not provided, uses settings.
        """
        self.api_key = api_key or settings.MANYCHAT_VERIFY_TOKEN
        self.base_url = MANYCHAT_API_BASE
        self._client: httpx.AsyncClient | None = None

    @property
    def headers(self) -> dict[str, str]:
        """Return authorization headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @property
    def is_configured(self) -> bool:
        """Check if ManyChat API is configured."""
        return bool(self.api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # =========================================================================
    # TAG MANAGEMENT
    # =========================================================================

    async def add_tag(self, subscriber_id: str, tag_name: str) -> bool:
        """Add a tag to subscriber.

        Args:
            subscriber_id: ManyChat subscriber ID
            tag_name: Tag name to add

        Returns:
            True if successful
        """
        if not self.is_configured:
            logger.warning("[MANYCHAT] API not configured, skipping add_tag")
            return False

        client = await self._get_client()
        try:
            response = await client.post(
                "/subscriber/addTagByName",
                json={
                    "subscriber_id": subscriber_id,
                    "tag_name": tag_name,
                },
            )
            response.raise_for_status()
            logger.info("[MANYCHAT] Added tag '%s' to subscriber %s", tag_name, subscriber_id)
            return True
        except httpx.HTTPStatusError as e:
            logger.error(
                "[MANYCHAT] Failed to add tag: %s - %s",
                e.response.status_code,
                e.response.text,
            )
            return False
        except Exception as e:
            logger.error("[MANYCHAT] Error adding tag: %s", e)
            return False

    async def remove_tag(self, subscriber_id: str, tag_name: str) -> bool:
        """Remove a tag from subscriber.

        Args:
            subscriber_id: ManyChat subscriber ID
            tag_name: Tag name to remove

        Returns:
            True if successful
        """
        if not self.is_configured:
            logger.warning("[MANYCHAT] API not configured, skipping remove_tag")
            return False

        client = await self._get_client()
        try:
            response = await client.post(
                "/subscriber/removeTagByName",
                json={
                    "subscriber_id": subscriber_id,
                    "tag_name": tag_name,
                },
            )
            response.raise_for_status()
            logger.info("[MANYCHAT] Removed tag '%s' from subscriber %s", tag_name, subscriber_id)
            return True
        except httpx.HTTPStatusError as e:
            logger.error(
                "[MANYCHAT] Failed to remove tag: %s - %s",
                e.response.status_code,
                e.response.text,
            )
            return False
        except Exception as e:
            logger.error("[MANYCHAT] Error removing tag: %s", e)
            return False

    # =========================================================================
    # CUSTOM FIELDS
    # =========================================================================

    async def set_custom_field(
        self,
        subscriber_id: str,
        field_name: str,
        field_value: str,
    ) -> bool:
        """Set a custom field value for subscriber.

        Args:
            subscriber_id: ManyChat subscriber ID
            field_name: Custom field name
            field_value: Value to set

        Returns:
            True if successful
        """
        if not self.is_configured:
            logger.warning("[MANYCHAT] API not configured, skipping set_custom_field")
            return False

        client = await self._get_client()
        try:
            response = await client.post(
                "/subscriber/setCustomFieldByName",
                json={
                    "subscriber_id": subscriber_id,
                    "field_name": field_name,
                    "field_value": field_value,
                },
            )
            response.raise_for_status()
            logger.info(
                "[MANYCHAT] Set field '%s'='%s' for subscriber %s",
                field_name,
                field_value[:50],
                subscriber_id,
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.error(
                "[MANYCHAT] Failed to set custom field: %s - %s",
                e.response.status_code,
                e.response.text,
            )
            return False
        except Exception as e:
            logger.error("[MANYCHAT] Error setting custom field: %s", e)
            return False

    async def set_custom_fields(
        self,
        subscriber_id: str,
        fields: dict[str, str],
    ) -> bool:
        """Set multiple custom fields for subscriber.

        Args:
            subscriber_id: ManyChat subscriber ID
            fields: Dict of field_name -> field_value

        Returns:
            True if all successful
        """
        if not fields:
            return True

        results = []
        for field_name, field_value in fields.items():
            result = await self.set_custom_field(subscriber_id, field_name, field_value)
            results.append(result)

        return all(results)

    # =========================================================================
    # SUBSCRIBER INFO
    # =========================================================================

    async def get_subscriber_info(self, subscriber_id: str) -> dict[str, Any] | None:
        """Get subscriber information.

        Args:
            subscriber_id: ManyChat subscriber ID

        Returns:
            Subscriber data dict or None if not found
        """
        if not self.is_configured:
            return None

        client = await self._get_client()
        try:
            response = await client.get(
                "/subscriber/getInfo",
                params={"subscriber_id": subscriber_id},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data")
        except Exception as e:
            logger.error("[MANYCHAT] Error getting subscriber info: %s", e)
            return None


# Singleton instance
_client: ManyChatClient | None = None


def get_manychat_client() -> ManyChatClient:
    """Get or create ManyChat API client singleton."""
    global _client
    if _client is None:
        _client = ManyChatClient()
    return _client


# Convenience functions for common operations


async def remove_ai_tag_from_subscriber(subscriber_id: str) -> bool:
    """Remove 'ai_responded' tag from subscriber after summarization.

    Called after 3-day summarization to mark conversation as inactive.
    """
    client = get_manychat_client()
    return await client.remove_tag(subscriber_id, "ai_responded")


async def update_subscriber_summary_fields(
    subscriber_id: str,
    last_order_sum: int | None = None,
    favorite_model: str | None = None,
    conversation_count: int | None = None,
) -> bool:
    """Update subscriber custom fields after summarization.

    Args:
        subscriber_id: ManyChat subscriber ID
        last_order_sum: Last order total (optional)
        favorite_model: Most discussed product (optional)
        conversation_count: Total conversations count (optional)

    Returns:
        True if successful
    """
    fields = {}
    if last_order_sum is not None:
        fields["last_order_sum"] = str(last_order_sum)
    if favorite_model:
        fields["favorite_model"] = favorite_model
    if conversation_count is not None:
        fields["conversation_count"] = str(conversation_count)

    if not fields:
        return True

    client = get_manychat_client()
    return await client.set_custom_fields(subscriber_id, fields)
