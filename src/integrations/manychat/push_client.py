"""ManyChat Push Client - sends messages via ManyChat API.

This module implements async push-based message delivery to ManyChat,
eliminating webhook timeout issues while preserving all MIRT features:
- Custom Fields (ai_state, ai_intent, last_product, order_sum)
- Tags (ai_responded, needs_human, order_started, order_paid)
- Quick Replies (state-based buttons)
- Images (product photos)

Auto-retry logic:
- If ManyChat returns 400 "Field not found" → retry WITHOUT actions
- This handles cases where Custom Fields don't exist in user's ManyChat bot
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from src.conf.config import settings
from src.core.circuit_breaker import MANYCHAT_BREAKER, CircuitOpenError
from src.core.human_responses import calculate_typing_delay


logger = logging.getLogger(__name__)

# Error patterns that trigger retry without actions
_FIELD_ERROR_PATTERNS = (
    "field with same name not found",
    "field not found",
    "wrong dynamic message format",
)


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

    def _sanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sanitize messages for ManyChat API format.
        
        ManyChat sendContent API format:
        - Text: {"type": "text", "text": "..."}
        - Image: {"type": "image", "url": "..."} (NO caption field!)
        """
        sanitized = []
        for msg in messages:
            msg_type = msg.get("type")
            if msg_type == "text":
                text = msg.get("text", "").strip()
                if text:
                    sanitized.append({"type": "text", "text": text})
            elif msg_type == "image":
                url = msg.get("url", "").strip()
                if url:
                    # ManyChat sendContent does NOT support caption for images
                    sanitized.append({"type": "image", "url": url})
            else:
                # Pass through other types as-is
                sanitized.append(msg)
        return sanitized

    def _build_actions(
        self,
        set_field_values: list[dict[str, Any]] | None,
        add_tags: list[str] | None,
        remove_tags: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Build actions list for ManyChat, respecting 5 action limit.
        
        IMPORTANT: ManyChat requires correct data types:
        - Number fields: numeric value (not string)
        - Text fields: string value
        - Boolean fields: true/false (not string)
        """
        actions: list[dict[str, Any]] = []

        # Add field values - preserve original types for ManyChat compatibility
        if set_field_values:
            for item in set_field_values:
                field_name = str(item.get("field_name") or "").strip()
                raw_value = item.get("field_value")

                if not field_name:
                    continue

                # Determine the correct value type for ManyChat
                if raw_value is None:
                    field_value: Any = ""
                elif isinstance(raw_value, bool):
                    # Boolean must stay boolean
                    field_value = raw_value
                elif isinstance(raw_value, (int, float)):
                    # Numbers must stay numeric
                    field_value = raw_value
                elif isinstance(raw_value, str):
                    # Try to parse numeric strings for Number fields
                    stripped = raw_value.strip()
                    if stripped.replace(".", "", 1).replace("-", "", 1).isdigit():
                        try:
                            field_value = float(stripped) if "." in stripped else int(stripped)
                        except ValueError:
                            field_value = stripped
                    else:
                        field_value = stripped
                else:
                    field_value = str(raw_value)

                actions.append({
                    "action": "set_field_value",
                    "field_name": field_name,
                    "value": field_value,
                })

        # Add tags
        if add_tags:
            for tag in add_tags:
                actions.append({"action": "add_tag", "tag_name": tag})

        # Remove tags
        if remove_tags:
            for tag in remove_tags:
                actions.append({"action": "remove_tag", "tag_name": tag})

        # ManyChat limits to 5 actions
        if len(actions) > 5:
            logger.warning("[MANYCHAT] Truncating actions from %d to 5", len(actions))
            actions = actions[:5]

        return actions

    async def _do_send(
        self,
        subscriber_id: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[bool, str, int]:
        """Execute the actual HTTP request with circuit breaker protection.
        
        Returns:
            (success, response_text, status_code)
        
        Raises:
            CircuitOpenError: If circuit breaker is open (ManyChat unavailable)
        """
        # CIRCUIT BREAKER CHECK: Fail fast if ManyChat is down
        if not MANYCHAT_BREAKER.can_execute():
            logger.warning(
                "[MANYCHAT] Circuit OPEN - skipping request to %s",
                subscriber_id,
            )
            raise CircuitOpenError("manychat")

        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self._api_url}/fb/sending/sendContent",
                    json=payload,
                    headers=headers,
                )

                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    # SUCCESS: Record for circuit breaker
                    MANYCHAT_BREAKER.record_success()
                    logger.debug(
                        "[MANYCHAT] Request OK in %.0fms",
                        latency_ms,
                    )
                elif response.status_code >= 500:
                    # SERVER ERROR: Record failure for circuit breaker
                    MANYCHAT_BREAKER.record_failure(
                        Exception(f"HTTP {response.status_code}")
                    )
                # 4xx errors don't trigger circuit breaker (client errors)

                return (
                    response.status_code == 200,
                    response.text,
                    response.status_code,
                )
        except httpx.TimeoutException as e:
            # TIMEOUT: Record failure for circuit breaker
            MANYCHAT_BREAKER.record_failure(e)
            return False, "timeout", 0
        except Exception as e:
            # OTHER ERROR: Record failure for circuit breaker
            MANYCHAT_BREAKER.record_failure(e)
            return False, str(e), 0

    def _is_field_error(self, response_text: str) -> bool:
        """Check if error is due to missing Custom Fields."""
        lower_text = response_text.lower()
        return any(pattern in lower_text for pattern in _FIELD_ERROR_PATTERNS)

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
        
        Auto-retry: If ManyChat returns 400 with 'Field not found' error,
        automatically retries WITHOUT actions (fields/tags).
        
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

        # Sanitize messages (remove unsupported fields like caption)
        clean_messages = self._sanitize_messages(messages)
        if not clean_messages:
            logger.warning("[MANYCHAT] No valid messages to send")
            return False

        # Build actions (may be empty)
        actions = self._build_actions(set_field_values, add_tags, remove_tags)

        # Build content structure
        content: dict[str, Any] = {
            "type": channel,
            "messages": clean_messages,
            "actions": actions,
        }
        if quick_replies:
            content["quick_replies"] = quick_replies

        # Build payload
        sub_id = int(subscriber_id) if subscriber_id.isdigit() else subscriber_id
        payload: dict[str, Any] = {
            "subscriber_id": sub_id,
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

        # TYPING DELAY: Simulate human typing speed
        total_text_length = sum(
            len(m.get("text", "")) for m in clean_messages if m.get("type") == "text"
        )
        delay = calculate_typing_delay(total_text_length)
        logger.debug("[MANYCHAT] Typing delay: %.2fs for %d chars", delay, total_text_length)
        await asyncio.sleep(delay)

        # First attempt with actions (with circuit breaker protection)
        try:
            success, response_text, status_code = await self._do_send(
                subscriber_id, payload, headers
            )
        except CircuitOpenError:
            # Circuit is open - ManyChat is down, fail gracefully
            logger.error(
                "[MANYCHAT] ❌ Circuit breaker OPEN - cannot send to %s",
                subscriber_id,
            )
            return False

        if success:
            logger.info(
                "[MANYCHAT] ✅ Pushed %d messages to %s (with %d actions)",
                len(clean_messages),
                subscriber_id,
                len(actions),
            )
            return True

        # Check if error is due to missing Custom Fields → retry without actions
        if status_code == 400 and actions and self._is_field_error(response_text):
            logger.warning(
                "[MANYCHAT] ⚠️ Field error detected, retrying WITHOUT actions: %s",
                response_text[:100],
            )

            # Rebuild payload without actions
            content_no_actions: dict[str, Any] = {
                "type": channel,
                "messages": clean_messages,
                "actions": [],  # Empty actions
            }
            if quick_replies:
                content_no_actions["quick_replies"] = quick_replies

            payload_retry: dict[str, Any] = {
                "subscriber_id": sub_id,
                "data": {
                    "version": "v2",
                    "content": content_no_actions,
                },
                "message_tag": message_tag,
            }

            try:
                success_retry, response_retry, status_retry = await self._do_send(
                    subscriber_id, payload_retry, headers
                )
            except CircuitOpenError:
                logger.error("[MANYCHAT] ❌ Circuit opened during retry")
                return False

            if success_retry:
                logger.info(
                    "[MANYCHAT] ✅ Pushed %d messages to %s (retry without actions)",
                    len(clean_messages),
                    subscriber_id,
                )
                return True
            else:
                logger.error(
                    "[MANYCHAT] ❌ Retry also failed: %d %s",
                    status_retry,
                    response_retry[:200],
                )
                return False

        # Other error - log and fail
        logger.error(
            "[MANYCHAT] ❌ Push failed: %d %s",
            status_code,
            response_text[:200],
        )
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
