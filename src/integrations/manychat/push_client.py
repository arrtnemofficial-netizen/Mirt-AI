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

import asyncio

import httpx

from src.conf.config import settings
from src.core.human_responses import calculate_typing_delay


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
        message_tag: str = "ACCOUNT_UPDATE",
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

        # Build actions for tags + custom fields (ManyChat v2 content format)
        required_field_names = {"ai_state", "ai_intent"}
        required_field_actions: list[dict[str, Any]] = []
        optional_field_actions: list[dict[str, Any]] = []
        tag_add_actions: list[dict[str, Any]] = []
        tag_remove_actions: list[dict[str, Any]] = []

        if set_field_values:
            for item in set_field_values:
                field_name = str(item.get("field_name") or "").strip()
                field_value = str(item.get("field_value") or "")
                if not field_name:
                    continue
                action = {
                    "action": "set_field_value",
                    "field_name": field_name,
                    "value": field_value,
                }
                if field_name in required_field_names:
                    required_field_actions.append(action)
                else:
                    optional_field_actions.append(action)

        if add_tags:
            for tag in add_tags:
                tag_add_actions.append({"action": "add_tag", "tag_name": tag})
        if remove_tags:
            for tag in remove_tags:
                tag_remove_actions.append({"action": "remove_tag", "tag_name": tag})

        # ManyChat Dynamic Block limits actions to 5.
        actions: list[dict[str, Any]] = (
            required_field_actions
            + tag_add_actions
            + tag_remove_actions
            + optional_field_actions
        )
        if len(actions) > 5:
            # Keep required field updates; trim the rest (least critical first)
            kept: list[dict[str, Any]] = list(required_field_actions)

            def _append_up_to(src: list[dict[str, Any]], target: list[dict[str, Any]], max_len: int) -> None:
                for a in src:
                    if len(target) >= max_len:
                        return
                    target.append(a)

            _append_up_to(tag_add_actions, kept, 5)
            _append_up_to(tag_remove_actions, kept, 5)
            _append_up_to(optional_field_actions, kept, 5)
            actions = kept

        if actions:
            content["actions"] = actions

        # Build payload
        payload: dict[str, Any] = {
            "subscriber_id": int(subscriber_id) if subscriber_id.isdigit() else subscriber_id,
            "data": {
                "version": "v2",
                "content": content,
            },
            "message_tag": message_tag,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        # TYPING DELAY: Simulate human typing speed (1-3 seconds)
        total_text_length = sum(
            len(m.get("text", "")) for m in messages if m.get("type") == "text"
        )
        delay = calculate_typing_delay(total_text_length)
        logger.debug("[MANYCHAT] Typing delay: %.2fs for %d chars", delay, total_text_length)
        await asyncio.sleep(delay)

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
