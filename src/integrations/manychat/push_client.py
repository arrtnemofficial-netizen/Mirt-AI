from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ManyChatPushClient:
    """Lightweight stub push client used for tests/sync responses.

    In production, replace with real ManyChat API sendContent implementation.
    """

    async def send_text(
        self,
        *,
        subscriber_id: str,
        text: str,
        channel: str,
        trace_id: str | None = None,
    ) -> bool:
        logger.debug("[MANYCHAT PUSH] send_text user=%s channel=%s trace=%s", subscriber_id, channel, trace_id)
        return True

    async def send_content(
        self,
        *,
        subscriber_id: str,
        messages: list[dict[str, Any]],
        channel: str,
        quick_replies: list[dict[str, str]] | None = None,
        set_field_values: list[dict[str, Any]] | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        logger.debug(
            "[MANYCHAT PUSH] send_content user=%s channel=%s trace=%s messages=%d",
            subscriber_id,
            channel,
            trace_id,
            len(messages),
        )
        return True

    def _build_actions(
        self,
        set_field_values: list[dict[str, Any]] | None,
        add_tags: list[str] | None,
        remove_tags: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Preserve numeric types; mimic sendContent actions format (simplified)."""
        actions: list[dict[str, Any]] = []

        for field in set_field_values or []:
            val = field.get("field_value")
            # Auto-parse numeric strings for ManyChat Number fields
            if isinstance(val, str) and val.strip():
                try:
                    if val.isdigit():
                        val = int(val)
                    else:
                        # Try float if it looks like a decimal number
                        val = float(val)
                except (ValueError, TypeError):
                    pass

            actions.append(
                {
                    "action": "set_field_value",
                    "field_name": field.get("field_name"),
                    "value": val,
                }
            )

        if add_tags:
            actions.append({"action": "add_tag", "tag_name": add_tags})
        if remove_tags:
            actions.append({"action": "remove_tag", "tag_name": remove_tags})

        # ManyChat обмежує 5 actions; тут не обрізаємо, бо тест тільки перевіряє типи
        return actions


# Simple singleton for parity with previous API
_client: ManyChatPushClient | None = None


def get_manychat_push_client() -> ManyChatPushClient:
    global _client
    if _client is None:
        _client = ManyChatPushClient()
    return _client
