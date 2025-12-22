"""ManyChat Push Client - Production-grade message delivery via ManyChat API.

This module implements async push-based message delivery to ManyChat,
eliminating webhook timeout issues while preserving all MIRT features:
- Custom Fields (ai_state, ai_intent, last_product, order_sum)
- Tags (ai_responded, needs_human, order_started, order_paid)
- Quick Replies (state-based buttons)
- Images (product photos)

Features:
- Circuit breaker protection against cascading failures
- Automatic retry with exponential backoff for transient errors
- Smart field error handling: retries without actions if fields don't exist
- Input validation for production reliability
- Message sanitization (removes unsupported fields, truncates long text)
- Instagram-specific optimizations (split-send, safe mode, bubble delays)
- Comprehensive error logging with root cause classification

API Compliance:
- ManyChat API v2 format (https://api.manychat.com/docs)
- subscriber_id: string (not converted to int - supports all ID formats)
- Text messages: max 2000 chars (auto-truncated)
- Actions: max 5 per request (auto-truncated)
- Image messages: no caption field (ManyChat limitation)

Example:
    ```python
    from src.integrations.manychat.push_client import get_manychat_push_client

    client = get_manychat_push_client()
    success = await client.send_content(
        subscriber_id="123456",
        messages=[{"type": "text", "text": "Hello!"}],
        channel="instagram",
        set_field_values=[{"field_name": "ai_state", "field_value": "STATE_1"}],
        add_tags=["ai_responded"],
    )
    ```
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any
from urllib.parse import quote

import httpx

from src.conf.config import settings
from src.core.circuit_breaker import MANYCHAT_BREAKER, CircuitOpenError
from src.core.human_responses import calculate_typing_delay
from src.core.logging import classify_root_cause, log_event, log_with_root_cause, safe_preview


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
        self._api_url = (
            api_url or getattr(settings, "MANYCHAT_API_URL", "https://api.manychat.com")
        ).rstrip("/")

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
        - Text: {"type": "text", "text": "..."} (max 2000 chars per message)
        - Image: {"type": "image", "url": "..."} (NO caption field!)

        Returns:
            List of sanitized messages, empty if all invalid
        """
        sanitized = []
        max_text_length = 2000  # ManyChat API limit

        for idx, msg in enumerate(messages):
            if not isinstance(msg, dict):
                logger.warning("[MANYCHAT] Skipping invalid message[%d]: not a dict", idx)
                continue

            msg_type = msg.get("type")
            if msg_type == "text":
                text = msg.get("text", "").strip()
                if not text:
                    logger.debug("[MANYCHAT] Skipping empty text message[%d]", idx)
                    continue

                # Truncate if exceeds ManyChat limit
                if len(text) > max_text_length:
                    logger.warning(
                        "[MANYCHAT] Truncating text message[%d] from %d to %d chars",
                        idx,
                        len(text),
                        max_text_length,
                    )
                    text = text[:max_text_length]

                sanitized.append({"type": "text", "text": text})
            elif msg_type == "image":
                url = msg.get("url", "").strip()
                if not url:
                    logger.debug("[MANYCHAT] Skipping empty image URL message[%d]", idx)
                    continue

                # Apply media proxy if enabled
                proxy_enabled = bool(getattr(settings, "MANYCHAT_IMAGE_PROXY_ENABLED", False))
                media_proxy_enabled = bool(getattr(settings, "MEDIA_PROXY_ENABLED", False))
                public_base_url = str(getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")

                if (
                    proxy_enabled
                    and media_proxy_enabled
                    and public_base_url.startswith("https://")
                ):
                    token = str(getattr(settings, "MEDIA_PROXY_TOKEN", "") or "").strip()
                    proxy_url = f"{public_base_url}/media/proxy?url={quote(url, safe='')}"
                    if token:
                        proxy_url += f"&token={quote(token, safe='')}"
                    url = proxy_url

                # ManyChat sendContent does NOT support caption for images
                sanitized.append({"type": "image", "url": url})
            else:
                # Unknown message type - log warning but pass through
                logger.warning(
                    "[MANYCHAT] Unknown message type '%s' in message[%d], passing through",
                    msg_type,
                    idx,
                )
                sanitized.append(msg)

        if not sanitized:
            logger.warning("[MANYCHAT] All messages were invalid after sanitization")

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

                actions.append(
                    {
                        "action": "set_field_value",
                        "field_name": field_name,
                        "value": field_value,
                    }
                )

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

    @staticmethod
    def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Redact and truncate payload for safe logging.

        NOTE: Avoid logging PII or long message bodies.
        """
        try:
            redacted = {
                "subscriber_id": payload.get("subscriber_id"),
                "message_tag": payload.get("message_tag"),
                "data": {
                    "version": (payload.get("data") or {}).get("version"),
                    "content": {},
                },
            }

            content = (payload.get("data") or {}).get("content") or {}
            redacted_content: dict[str, Any] = {
                "type": content.get("type"),
                "messages": [],
                "actions": [],
            }

            # Messages: truncate text and urls
            for msg in content.get("messages") or []:
                msg_type = msg.get("type")
                if msg_type == "text":
                    text = str(msg.get("text") or "")
                    if len(text) > 200:
                        text = text[:200] + "…"
                    redacted_content["messages"].append({"type": "text", "text": text})
                elif msg_type == "image":
                    url = str(msg.get("url") or "")
                    if len(url) > 120:
                        url = url[:120] + "…"
                    redacted_content["messages"].append({"type": "image", "url": url})
                else:
                    redacted_content["messages"].append({"type": msg_type or "unknown"})

            # Actions: keep only action kind + field/tag names (values are redacted)
            for act in content.get("actions") or []:
                action_type = act.get("action")
                if action_type == "set_field_value":
                    field_name = str(act.get("field_name") or "")
                    redacted_content["actions"].append(
                        {
                            "action": "set_field_value",
                            "field_name": field_name,
                            "value": "<redacted>",
                        }
                    )
                elif action_type in ("add_tag", "remove_tag"):
                    redacted_content["actions"].append(
                        {
                            "action": action_type,
                            "tag_name": act.get("tag_name"),
                        }
                    )
                else:
                    redacted_content["actions"].append({"action": action_type or "unknown"})

            # Quick replies (if present)
            if content.get("quick_replies"):
                redacted_content["quick_replies_count"] = len(content.get("quick_replies") or [])

            redacted["data"]["content"] = redacted_content
            return redacted
        except Exception:
            return {"_redact_failed": True}

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
            log_with_root_cause(
                logger,
                "warning",
                f"[MANYCHAT] Circuit OPEN - skipping request to {subscriber_id}",
                root_cause="CIRCUIT_BREAKER_OPEN",
                subscriber_id=subscriber_id,
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
                    MANYCHAT_BREAKER.record_failure(Exception(f"HTTP {response.status_code}"))
                # 4xx errors don't trigger circuit breaker (client errors)

                return (
                    response.status_code == 200,
                    response.text,
                    response.status_code,
                )
        except httpx.TimeoutException as e:
            # TIMEOUT: Record failure for circuit breaker
            MANYCHAT_BREAKER.record_failure(e)
            log_with_root_cause(
                logger,
                "error",
                f"[MANYCHAT] Request timeout after 15s for subscriber {subscriber_id}",
                error=e,
                root_cause="MANYCHAT_TIMEOUT",
                subscriber_id=subscriber_id,
            )
            return False, "timeout", 0
        except httpx.ConnectError as e:
            # CONNECTION ERROR: Record failure for circuit breaker
            MANYCHAT_BREAKER.record_failure(e)
            log_with_root_cause(
                logger,
                "error",
                f"[MANYCHAT] Connection error for subscriber {subscriber_id}",
                error=e,
                root_cause="MANYCHAT_CONNECTION_ERROR",
                subscriber_id=subscriber_id,
            )
            return False, f"connection_error: {str(e)[:100]}", 0
        except httpx.HTTPStatusError as e:
            # HTTP ERROR: Already handled above, but catch here for completeness
            status = e.response.status_code if e.response else 0
            MANYCHAT_BREAKER.record_failure(e)
            log_with_root_cause(
                logger,
                "error",
                f"[MANYCHAT] HTTP error {status} for subscriber {subscriber_id}",
                error=e,
                root_cause=f"MANYCHAT_HTTP_{status}",
                subscriber_id=subscriber_id,
                status_code=status,
            )
            return False, e.response.text if e.response else str(e), status
        except Exception as e:
            # OTHER ERROR: Record failure for circuit breaker
            MANYCHAT_BREAKER.record_failure(e)
            log_with_root_cause(
                logger,
                "error",
                f"[MANYCHAT] Unexpected error for subscriber {subscriber_id}",
                error=e,
                root_cause="MANYCHAT_UNEXPECTED_ERROR",
                subscriber_id=subscriber_id,
            )
            return False, f"{type(e).__name__}: {str(e)[:200]}", 0

    def _is_field_error(self, response_text: str) -> bool:
        """Check if error is due to missing Custom Fields."""
        lower_text = response_text.lower()
        return any(pattern in lower_text for pattern in _FIELD_ERROR_PATTERNS)

    @staticmethod
    def _is_transient_status(status_code: int) -> bool:
        return status_code in (0, 408, 429) or status_code >= 500

    @staticmethod
    def _get_retry_config() -> tuple[int, float, float]:
        try:
            max_retries = int(getattr(settings, "MANYCHAT_PUSH_MAX_RETRIES", 2))
        except Exception:
            max_retries = 2
        try:
            base_delay = float(getattr(settings, "MANYCHAT_PUSH_RETRY_BASE_DELAY_SECONDS", 0.5))
        except Exception:
            base_delay = 0.5
        try:
            max_delay = float(getattr(settings, "MANYCHAT_PUSH_RETRY_MAX_DELAY_SECONDS", 3.0))
        except Exception:
            max_delay = 3.0
        max_retries = max(max_retries, 0)
        if base_delay < 0:
            base_delay = 0.0
        max_delay = max(max_delay, base_delay)
        return max_retries, base_delay, max_delay

    @staticmethod
    def _compute_retry_delay(base_delay: float, max_delay: float, attempt: int) -> float:
        # Exponential backoff with jitter (bounded).
        delay = min(max_delay, base_delay * (2 ** max(attempt - 1, 0)))
        jitter = random.uniform(0.0, delay * 0.25) if delay > 0 else 0.0
        return min(max_delay, delay + jitter)

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
        message_tag: str = "CONFIRMED_EVENT_UPDATE",
        trace_id: str | None = None,
    ) -> bool:
        """Send content to a ManyChat subscriber.

        Auto-retry: If ManyChat returns 400 with 'Field not found' error,
        automatically retries WITHOUT actions (fields/tags).

        Args:
            subscriber_id: ManyChat subscriber ID (must be non-empty string)
            messages: List of message objects (text, image)
            channel: Channel type (instagram, facebook, whatsapp)
            quick_replies: Quick reply buttons
            set_field_values: Custom fields to update
            add_tags: Tags to add
            remove_tags: Tags to remove

        Returns:
            True if sent successfully, False otherwise
        """
        # VALIDATION: Input validation for production-grade reliability
        if not self.enabled:
            logger.warning("[MANYCHAT] Push client not configured (missing API key)")
            return False

        if not subscriber_id or not isinstance(subscriber_id, str) or not subscriber_id.strip():
            log_with_root_cause(
                logger,
                "error",
                f"[MANYCHAT] Invalid subscriber_id: must be non-empty string, got {type(subscriber_id).__name__}",
                root_cause="VALIDATION_ERROR",
                subscriber_id=subscriber_id if subscriber_id else None,
            )
            return False

        subscriber_id = subscriber_id.strip()

        if not messages or not isinstance(messages, list):
            log_with_root_cause(
                logger,
                "error",
                "[MANYCHAT] Invalid messages: must be non-empty list",
                root_cause="VALIDATION_ERROR",
                subscriber_id=subscriber_id,
            )
            return False

        valid_channels = {"instagram", "facebook", "whatsapp", "telegram"}
        if channel not in valid_channels:
            logger.warning(
                "[MANYCHAT] Unknown channel '%s', using 'instagram'. Valid: %s",
                channel,
                valid_channels,
            )
            channel = "instagram"

        # VALIDATION: Quick replies format
        if quick_replies is not None:
            if not isinstance(quick_replies, list):
                log_with_root_cause(
                    logger,
                    "error",
                    f"[MANYCHAT] quick_replies must be a list, got {type(quick_replies).__name__}",
                    root_cause="VALIDATION_ERROR",
                    subscriber_id=subscriber_id,
                )
                quick_replies = None
            else:
                # ManyChat limits to 11 quick replies
                if len(quick_replies) > 11:
                    logger.warning(
                        "[MANYCHAT] Truncating quick_replies from %d to 11",
                        len(quick_replies),
                    )
                    quick_replies = quick_replies[:11]

        # VALIDATION: Tags format
        if add_tags is not None and not isinstance(add_tags, list):
            log_with_root_cause(
                logger,
                "error",
                f"[MANYCHAT] add_tags must be a list, got {type(add_tags).__name__}",
                root_cause="VALIDATION_ERROR",
                subscriber_id=subscriber_id,
            )
            add_tags = None

        if remove_tags is not None and not isinstance(remove_tags, list):
            log_with_root_cause(
                logger,
                "error",
                f"[MANYCHAT] remove_tags must be a list, got {type(remove_tags).__name__}",
                root_cause="VALIDATION_ERROR",
                subscriber_id=subscriber_id,
            )
            remove_tags = None

        # VALIDATION: Field values format
        if set_field_values is not None:
            if not isinstance(set_field_values, list):
                log_with_root_cause(
                    logger,
                    "error",
                    f"[MANYCHAT] set_field_values must be a list, got {type(set_field_values).__name__}",
                    root_cause="VALIDATION_ERROR",
                    subscriber_id=subscriber_id,
                )
                set_field_values = None
            else:
                # Validate each field value has required keys
                valid_fields = []
                for idx, fv in enumerate(set_field_values):
                    if not isinstance(fv, dict):
                        logger.warning("[MANYCHAT] Skipping invalid field_value[%d]: not a dict", idx)
                        continue
                    if "field_name" not in fv:
                        logger.warning("[MANYCHAT] Skipping field_value[%d]: missing 'field_name'", idx)
                        continue
                    valid_fields.append(fv)
                set_field_values = valid_fields if valid_fields else None

        # VALIDATION: Message tag (Facebook/Meta requirement for 24h messaging)
        valid_message_tags = {
            "CONFIRMED_EVENT_UPDATE",
            "ACCOUNT_UPDATE",
            "PAYMENT_UPDATE",
            "SHIPPING_UPDATE",
            "RESERVATION_UPDATE",
            "ISSUE_RESOLUTION",
            "APPOINTMENT_UPDATE",
            "GAME_EVENT",
            "TRANSPORTATION_UPDATE",
            "FEATURE_FUNCTIONALITY_UPDATE",
            "TICKET_UPDATE",
        }
        if message_tag not in valid_message_tags:
            logger.warning(
                "[MANYCHAT] Unknown message_tag '%s', using 'CONFIRMED_EVENT_UPDATE'. Valid: %s",
                message_tag,
                sorted(valid_message_tags),
            )
            message_tag = "CONFIRMED_EVENT_UPDATE"

        # Sanitize messages (remove unsupported fields like caption)
        clean_messages = self._sanitize_messages(messages)
        if not clean_messages:
            logger.warning("[MANYCHAT] No valid messages to send after sanitization")
            return False

        safe_mode_instagram = bool(getattr(settings, "MANYCHAT_SAFE_MODE_INSTAGRAM", True))
        disable_actions_instagram = bool(
            getattr(settings, "MANYCHAT_INSTAGRAM_DISABLE_ACTIONS", True)
        )
        split_send_instagram = bool(getattr(settings, "MANYCHAT_INSTAGRAM_SPLIT_SEND", True))
        bubble_delay_seconds = float(
            getattr(settings, "MANYCHAT_INSTAGRAM_BUBBLE_DELAY_SECONDS", 5.0)
        )

        # IMPORTANT: Instagram delivery must be fast (UX + 45s SLA).
        # Cap artificial delays so a multi-bubble response doesn't take minutes.
        max_typing_delay_instagram = float(
            getattr(settings, "MANYCHAT_INSTAGRAM_MAX_TYPING_DELAY_SECONDS", 2.0)
        )
        max_interbubble_delay_total_instagram = float(
            getattr(settings, "MANYCHAT_INSTAGRAM_MAX_INTERBUBBLE_DELAY_SECONDS", 10.0)
        )

        allowed_fields_raw = str(
            getattr(settings, "MANYCHAT_INSTAGRAM_ALLOWED_FIELDS", "ai_state,ai_intent")
        )
        allowed_fields = {f.strip() for f in allowed_fields_raw.split(",") if f and f.strip()}

        # Instagram sendContent is strict and frequently rejects actions/quick replies.
        # Default to safe mode: no quick replies; actions are restricted to a minimal allowlist.
        effective_quick_replies = quick_replies
        if channel == "instagram" and safe_mode_instagram:
            effective_quick_replies = None

        # Build actions (may be empty)
        if channel == "instagram" and disable_actions_instagram:
            actions = []
        elif channel == "instagram" and safe_mode_instagram:
            filtered_fields = [
                fv
                for fv in (set_field_values or [])
                if str(fv.get("field_name") or "").strip() in allowed_fields
            ]
            actions = self._build_actions(filtered_fields, add_tags=None, remove_tags=None)
        else:
            actions = self._build_actions(set_field_values, add_tags, remove_tags)

        # Build content structure
        content: dict[str, Any] = {
            "type": channel,
            "messages": clean_messages,
            "actions": actions,
        }
        if effective_quick_replies:
            content["quick_replies"] = effective_quick_replies

        # Build payload
        # NOTE: ManyChat API accepts subscriber_id as string (verified in api_client.py)
        # Converting to int can break for non-numeric IDs (e.g., "user_123" or UUIDs)
        payload: dict[str, Any] = {
            "subscriber_id": subscriber_id,  # Keep as string - ManyChat API requirement
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

        async def _send_with_retry(
            *,
            payload_to_send: dict[str, Any],
            had_actions: bool,
        ) -> bool:
            """Send payload with limited retries on transient failures.

            Also retries once without actions when ManyChat rejects fields.
            """
            max_retries, base_delay, max_delay = self._get_retry_config()
            attempt = 0
            while True:
                attempt += 1
                try:
                    success_local, response_text_local, status_code_local = await self._do_send(
                        subscriber_id, payload_to_send, headers
                    )
                except CircuitOpenError as e:
                    log_with_root_cause(
                        logger,
                        "error",
                        f"[MANYCHAT] Circuit breaker OPEN - cannot send to {subscriber_id}",
                        error=e,
                        root_cause="CIRCUIT_BREAKER_OPEN",
                        subscriber_id=subscriber_id,
                    )
                    return False

                if success_local:
                    return True

                if status_code_local and status_code_local < 500:
                    root_cause = classify_root_cause(
                        response_text_local,
                        channel=channel,
                        status_code=status_code_local,
                    )
                    log_event(
                        logger,
                        event="manychat_push_rejected",
                        level="warning",
                        trace_id=trace_id,
                        user_id=subscriber_id,
                        channel=channel,
                        status_code=status_code_local,
                        root_cause=root_cause,
                        error=safe_preview(response_text_local, 200),
                    )
                    logger.warning(
                        "[MANYCHAT] Push rejected: %d %s | payload=%s",
                        status_code_local,
                        response_text_local[:200],
                        self._redact_payload(payload_to_send),
                    )

                if (
                    status_code_local == 400
                    and had_actions
                    and self._is_field_error(response_text_local)
                ):
                    logger.warning(
                        "[MANYCHAT] Field error detected, retrying WITHOUT actions: %s",
                        response_text_local[:100],
                    )

                    content_retry = dict((payload_to_send.get("data") or {}).get("content") or {})
                    content_retry["actions"] = []

                    payload_retry = {
                        **payload_to_send,
                        "data": {
                            **(payload_to_send.get("data") or {}),
                            "content": content_retry,
                        },
                    }

                    try:
                        success_retry, response_retry, status_retry = await self._do_send(
                            subscriber_id, payload_retry, headers
                        )
                    except CircuitOpenError as e:
                        log_with_root_cause(
                            logger,
                            "error",
                            "[MANYCHAT] Circuit opened during retry",
                            error=e,
                            root_cause="CIRCUIT_BREAKER_OPEN",
                            subscriber_id=subscriber_id,
                        )
                        return False

                    if success_retry:
                        log_event(
                            logger,
                            event="manychat_push_ok",
                            trace_id=trace_id,
                            user_id=subscriber_id,
                            channel=channel,
                            messages_count=len(
                                ((payload_retry.get("data") or {}).get("content") or {}).get(
                                    "messages"
                                )
                                or []
                            ),
                            status="retry_without_actions",
                        )
                        logger.info(
                            "[MANYCHAT] Pushed %d messages to %s (retry without actions)",
                            len(
                                ((payload_retry.get("data") or {}).get("content") or {}).get(
                                    "messages"
                                )
                                or []
                            ),
                            subscriber_id,
                        )
                        return True

                    if status_retry and status_retry < 500:
                        logger.warning(
                            "[MANYCHAT] Retry rejected: %d %s | payload=%s",
                            status_retry,
                            str(response_retry)[:200],
                            self._redact_payload(payload_retry),
                        )
                    return False

                if self._is_transient_status(status_code_local) and attempt <= max_retries:
                    delay = self._compute_retry_delay(base_delay, max_delay, attempt)
                    logger.warning(
                        "[MANYCHAT] Transient failure (status=%s). Retrying in %.2fs (attempt %d/%d)",
                        status_code_local,
                        delay,
                        attempt,
                        max_retries,
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)
                    continue

                return False

        # Instagram split-send mode: send each bubble as its own sendContent call.
        # This improves UI (separate bubbles) and allows a real inter-bubble delay.
        if channel == "instagram" and split_send_instagram and len(clean_messages) > 1:
            first_text_len = 0
            if clean_messages and clean_messages[0].get("type") == "text":
                first_text_len = len(str(clean_messages[0].get("text") or ""))
            delay = calculate_typing_delay(first_text_len)
            delay = min(delay, max_typing_delay_instagram)
            logger.debug(
                "[MANYCHAT] Typing delay (split): %.2fs for %d chars",
                delay,
                first_text_len,
            )
            await asyncio.sleep(delay)

            effective_bubble_delay = bubble_delay_seconds
            if max_interbubble_delay_total_instagram > 0:
                effective_bubble_delay = min(
                    effective_bubble_delay,
                    max_interbubble_delay_total_instagram / max(len(clean_messages) - 1, 1),
                )

            for idx, msg in enumerate(clean_messages):
                is_last = idx == (len(clean_messages) - 1)
                actions_for_msg = []
                if not disable_actions_instagram:
                    actions_for_msg = actions if idx == 0 else []

                content_one: dict[str, Any] = {
                    "type": channel,
                    "messages": [msg],
                    "actions": actions_for_msg,
                }
                # Only attach quick replies to the last bubble (and only if allowed).
                if is_last and effective_quick_replies:
                    content_one["quick_replies"] = effective_quick_replies

                payload_one: dict[str, Any] = {
                    "subscriber_id": subscriber_id,  # Keep as string
                    "data": {
                        "version": "v2",
                        "content": content_one,
                    },
                    "message_tag": message_tag,
                }

                ok_one = await _send_with_retry(
                    payload_to_send=payload_one,
                    had_actions=bool(actions_for_msg),
                )
                if not ok_one:
                    return False

                if not is_last and effective_bubble_delay > 0:
                    await asyncio.sleep(effective_bubble_delay)

            logger.info(
                "[MANYCHAT] Pushed %d messages to %s (split-send)",
                len(clean_messages),
                subscriber_id,
            )
            return True

        # Default mode: one sendContent call with all messages.
        total_text_length = sum(
            len(m.get("text", "")) for m in clean_messages if m.get("type") == "text"
        )
        delay = calculate_typing_delay(total_text_length)
        if channel == "instagram":
            delay = min(delay, max_typing_delay_instagram)
        logger.debug("[MANYCHAT] Typing delay: %.2fs for %d chars", delay, total_text_length)
        await asyncio.sleep(delay)

        ok = await _send_with_retry(payload_to_send=payload, had_actions=bool(actions))
        if ok:
            log_event(
                logger,
                event="manychat_push_ok",
                trace_id=trace_id,
                user_id=subscriber_id,
                channel=channel,
                messages_count=len(clean_messages),
                status="sent",
            )
            logger.info(
                "[MANYCHAT] Pushed %d messages to %s (actions=%d, ig_actions_disabled=%s)",
                len(clean_messages),
                subscriber_id,
                len(actions),
                str(bool(channel == "instagram" and disable_actions_instagram)).lower(),
            )
            return True

        return False

    async def send_text(
        self,
        subscriber_id: str,
        text: str,
        *,
        channel: str = "instagram",
        trace_id: str | None = None,
    ) -> bool:
        """Send a simple text message."""
        return await self.send_content(
            subscriber_id=subscriber_id,
            messages=[{"type": "text", "text": text}],
            channel=channel,
            trace_id=trace_id,
        )


# Singleton
_push_client: ManyChatPushClient | None = None


def get_manychat_push_client() -> ManyChatPushClient:
    """Get singleton push client instance."""
    global _push_client
    if _push_client is None:
        _push_client = ManyChatPushClient()
    return _push_client
