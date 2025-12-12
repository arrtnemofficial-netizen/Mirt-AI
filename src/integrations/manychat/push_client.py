"""ManyChat Push Client - sends messages via ManyChat API.

This module implements async push-based message delivery to ManyChat,
eliminating webhook timeout issues while preserving all MIRT features:
- Custom Fields (ai_state, ai_intent, last_product, order_sum)
- Tags (ai_responded, needs_human, order_started, order_paid)
- Quick Replies (state-based buttons)
- Images (product photos)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.conf.config import settings


logger = logging.getLogger(__name__)


class ManyChatPushClient:
    """Client for pushing messages to ManyChat via their API."""

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or getattr(settings, "MANYCHAT_API_URL", "https://api.manychat.com")).rstrip("/")
        
        # Handle SecretStr
        api_key_setting = api_key or getattr(settings, "MANYCHAT_API_KEY", None)
        if api_key_setting and hasattr(api_key_setting, "get_secret_value"):
            self._api_key = api_key_setting.get_secret_value()
        else:
            self._api_key = str(api_key_setting) if api_key_setting else ""

    @property
    def enabled(self) -> bool:
        """Check if push mode is configured."""
        return bool(self._api_url and self._api_key)

    async def send_content(
        self,
        subscriber_id: str,
        messages: list[dict[str, Any]],
        *,
        channel: str = "instagram",
        quick_replies: list[dict[str, str]] | None = None,
        set_field_values: list[dict[str, str]] | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
    ) -> bool:
        """Send content to a ManyChat subscriber.
        
        Args:
            subscriber_id: ManyChat subscriber ID
            messages: List of message objects (text, image)
            channel: Channel type (instagram, facebook, whatsapp)
            quick_replies: Quick reply buttons
            set_field_values: Custom fields to update
            add_tags: Tags to add
            remove_tags: Tags to remove
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled:
            logger.warning("[MANYCHAT] Push client not configured (missing API key)")
            return False

        # Build content structure
        content: dict[str, Any] = {
            "type": channel,
            "messages": messages,
        }

        if quick_replies:
            content["quick_replies"] = quick_replies

        # Build actions for tags
        actions: list[dict[str, Any]] = []
        if add_tags:
            for tag in add_tags:
                actions.append({"action": "add_tag", "tag_name": tag})
        if remove_tags:
            for tag in remove_tags:
                actions.append({"action": "remove_tag", "tag_name": tag})
        
        if actions:
            content["actions"] = actions

        # Build payload
        payload: dict[str, Any] = {
            "subscriber_id": int(subscriber_id) if subscriber_id.isdigit() else subscriber_id,
            "data": {
                "version": "v2",
                "content": content,
            },
        }

        # Add field values at top level (ManyChat API format)
        if set_field_values:
            payload["data"]["set_field_values"] = set_field_values

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self._api_url}/fb/sending/sendContent",
                    json=payload,
                    headers=headers,
                )
                
                if response.status_code == 200:
                    logger.info(
                        "[MANYCHAT] ✅ Pushed message to subscriber %s (%d messages)",
                        subscriber_id,
                        len(messages),
                    )
                    return True
                else:
                    logger.error(
                        "[MANYCHAT] ❌ Push failed: %d %s",
                        response.status_code,
                        response.text[:200],
                    )
                    return False

        except httpx.TimeoutException:
            logger.error("[MANYCHAT] Push timeout for subscriber %s", subscriber_id)
            return False
        except Exception as e:
            logger.exception("[MANYCHAT] Push error: %s", e)
            return False

    async def send_text(
        self,
        subscriber_id: str,
        text: str,
        *,
        channel: str = "instagram",
    ) -> bool:
        """Send a simple text message."""
        return await self.send_content(
            subscriber_id=subscriber_id,
            messages=[{"type": "text", "text": text}],
            channel=channel,
        )


# Singleton
_push_client: ManyChatPushClient | None = None


def get_manychat_push_client() -> ManyChatPushClient:
    """Get singleton push client instance."""
    global _push_client
    if _push_client is None:
        _push_client = ManyChatPushClient()
    return _push_client
