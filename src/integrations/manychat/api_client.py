"""ManyChat API client for subscriber management.

This module provides FULL ManyChat API integration:
- Send messages (text, images, cards, galleries)
- Add/remove tags from subscribers
- Update custom fields
- Trigger flows
- Get subscriber info

Documentation: https://api.manychat.com/docs

SETUP IN MANYCHAT:
1. Go to Settings → API → Get API Key
2. Add to .env: MANYCHAT_API_KEY=your_key_here
3. Create Custom Fields: ai_state, ai_response, last_product
4. Create Tags: ai_responded, ai_followup_pending, order_created
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
    """Full ManyChat API client.
    
    Usage:
        client = ManyChatClient()
        
        # Send text message
        await client.send_message(subscriber_id, "Привіт!")
        
        # Send with buttons
        await client.send_message_with_buttons(
            subscriber_id,
            "Оберіть розмір:",
            [{"title": "S", "payload": "size_s"}, {"title": "M", "payload": "size_m"}]
        )
        
        # Send product card
        await client.send_card(
            subscriber_id,
            title="Сукня Анна",
            image_url="https://...",
            subtitle="1200 грн",
            buttons=[{"title": "Замовити", "payload": "order"}]
        )
    """

    def __init__(self, api_key: str | None = None):
        """Initialize ManyChat API client.

        Args:
            api_key: ManyChat API key. If not provided, uses settings.
        """
        # Prefer dedicated API key, fallback to verify token
        self.api_key = (
            api_key
            or settings.MANYCHAT_API_KEY.get_secret_value()
            or settings.MANYCHAT_VERIFY_TOKEN
        )
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
    # SENDING MESSAGES (NEW!)
    # =========================================================================

    async def send_message(
        self,
        subscriber_id: str,
        text: str,
        message_tag: str = "CONFIRMED_EVENT_UPDATE",
    ) -> bool:
        """Send a text message to subscriber.

        Args:
            subscriber_id: ManyChat subscriber ID
            text: Message text (max 2048 chars)
            message_tag: Facebook message tag for sending outside 24h window

        Returns:
            True if successful
        """
        if not self.is_configured:
            logger.warning("[MANYCHAT] API not configured, skipping send_message")
            return False

        client = await self._get_client()
        try:
            response = await client.post(
                "/sending/sendContent",
                json={
                    "subscriber_id": subscriber_id,
                    "data": {
                        "version": "v2",
                        "content": {
                            "messages": [{"type": "text", "text": text[:2048]}],
                        },
                    },
                    "message_tag": message_tag,
                },
            )
            response.raise_for_status()
            logger.info("[MANYCHAT] Sent message to %s: %s", subscriber_id, text[:50])
            return True
        except httpx.HTTPStatusError as e:
            logger.error(
                "[MANYCHAT] Failed to send message: %s - %s",
                e.response.status_code,
                e.response.text,
            )
            return False
        except Exception as e:
            logger.error("[MANYCHAT] Error sending message: %s", e)
            return False

    async def send_message_with_buttons(
        self,
        subscriber_id: str,
        text: str,
        buttons: list[dict[str, str]],
        message_tag: str = "CONFIRMED_EVENT_UPDATE",
    ) -> bool:
        """Send a text message with quick reply buttons.

        Args:
            subscriber_id: ManyChat subscriber ID
            text: Message text
            buttons: List of buttons [{"title": "Button", "payload": "action"}]
            message_tag: Facebook message tag

        Returns:
            True if successful
        """
        if not self.is_configured:
            return False

        # Format buttons for ManyChat
        formatted_buttons = [
            {"type": "reply", "title": btn["title"], "payload": btn.get("payload", btn["title"])}
            for btn in buttons[:11]  # Max 11 quick replies
        ]

        client = await self._get_client()
        try:
            response = await client.post(
                "/sending/sendContent",
                json={
                    "subscriber_id": subscriber_id,
                    "data": {
                        "version": "v2",
                        "content": {
                            "messages": [
                                {
                                    "type": "text",
                                    "text": text[:2048],
                                    "buttons": formatted_buttons,
                                }
                            ],
                        },
                    },
                    "message_tag": message_tag,
                },
            )
            response.raise_for_status()
            logger.info("[MANYCHAT] Sent message with buttons to %s", subscriber_id)
            return True
        except Exception as e:
            logger.error("[MANYCHAT] Error sending message with buttons: %s", e)
            return False

    async def send_card(
        self,
        subscriber_id: str,
        title: str,
        image_url: str | None = None,
        subtitle: str | None = None,
        buttons: list[dict[str, str]] | None = None,
        message_tag: str = "CONFIRMED_EVENT_UPDATE",
    ) -> bool:
        """Send a card (product) to subscriber.

        Args:
            subscriber_id: ManyChat subscriber ID
            title: Card title
            image_url: Product image URL
            subtitle: Card subtitle (e.g., price)
            buttons: Action buttons
            message_tag: Facebook message tag

        Returns:
            True if successful
        """
        if not self.is_configured:
            return False

        card = {"title": title[:80]}
        if image_url:
            card["image_url"] = image_url
        if subtitle:
            card["subtitle"] = subtitle[:80]
        if buttons:
            card["buttons"] = [
                {"type": "postback", "title": btn["title"], "payload": btn.get("payload", btn["title"])}
                for btn in buttons[:3]  # Max 3 buttons per card
            ]

        client = await self._get_client()
        try:
            response = await client.post(
                "/sending/sendContent",
                json={
                    "subscriber_id": subscriber_id,
                    "data": {
                        "version": "v2",
                        "content": {
                            "messages": [
                                {
                                    "type": "cards",
                                    "elements": [card],
                                    "image_aspect_ratio": "square",
                                }
                            ],
                        },
                    },
                    "message_tag": message_tag,
                },
            )
            response.raise_for_status()
            logger.info("[MANYCHAT] Sent card to %s: %s", subscriber_id, title)
            return True
        except Exception as e:
            logger.error("[MANYCHAT] Error sending card: %s", e)
            return False

    async def send_gallery(
        self,
        subscriber_id: str,
        items: list[dict[str, Any]],
        message_tag: str = "CONFIRMED_EVENT_UPDATE",
    ) -> bool:
        """Send a product gallery (carousel) to subscriber.

        Args:
            subscriber_id: ManyChat subscriber ID
            items: List of products [{title, image_url, subtitle, buttons}]
            message_tag: Facebook message tag

        Returns:
            True if successful
        """
        if not self.is_configured:
            return False

        elements = []
        for item in items[:10]:  # Max 10 cards
            card = {"title": item.get("title", "Product")[:80]}
            if item.get("image_url"):
                card["image_url"] = item["image_url"]
            if item.get("subtitle"):
                card["subtitle"] = item["subtitle"][:80]
            if item.get("buttons"):
                card["buttons"] = [
                    {"type": "postback", "title": btn["title"], "payload": btn.get("payload", btn["title"])}
                    for btn in item["buttons"][:3]
                ]
            elements.append(card)

        client = await self._get_client()
        try:
            response = await client.post(
                "/sending/sendContent",
                json={
                    "subscriber_id": subscriber_id,
                    "data": {
                        "version": "v2",
                        "content": {
                            "messages": [
                                {
                                    "type": "cards",
                                    "elements": elements,
                                    "image_aspect_ratio": "square",
                                }
                            ],
                        },
                    },
                    "message_tag": message_tag,
                },
            )
            response.raise_for_status()
            logger.info("[MANYCHAT] Sent gallery with %d items to %s", len(elements), subscriber_id)
            return True
        except Exception as e:
            logger.error("[MANYCHAT] Error sending gallery: %s", e)
            return False

    async def send_image(
        self,
        subscriber_id: str,
        image_url: str,
        message_tag: str = "CONFIRMED_EVENT_UPDATE",
    ) -> bool:
        """Send an image to subscriber.

        Args:
            subscriber_id: ManyChat subscriber ID
            image_url: Image URL
            message_tag: Facebook message tag

        Returns:
            True if successful
        """
        if not self.is_configured:
            return False

        client = await self._get_client()
        try:
            response = await client.post(
                "/sending/sendContent",
                json={
                    "subscriber_id": subscriber_id,
                    "data": {
                        "version": "v2",
                        "content": {
                            "messages": [{"type": "image", "url": image_url}],
                        },
                    },
                    "message_tag": message_tag,
                },
            )
            response.raise_for_status()
            logger.info("[MANYCHAT] Sent image to %s", subscriber_id)
            return True
        except Exception as e:
            logger.error("[MANYCHAT] Error sending image: %s", e)
            return False

    # =========================================================================
    # FLOW TRIGGERS (NEW!)
    # =========================================================================

    async def trigger_flow(
        self,
        subscriber_id: str,
        flow_ns: str,
    ) -> bool:
        """Trigger a ManyChat flow for subscriber.

        Args:
            subscriber_id: ManyChat subscriber ID
            flow_ns: Flow namespace (from ManyChat flow URL)

        Returns:
            True if successful
        """
        if not self.is_configured:
            return False

        client = await self._get_client()
        try:
            response = await client.post(
                "/sending/sendFlow",
                json={
                    "subscriber_id": subscriber_id,
                    "flow_ns": flow_ns,
                },
            )
            response.raise_for_status()
            logger.info("[MANYCHAT] Triggered flow %s for %s", flow_ns, subscriber_id)
            return True
        except Exception as e:
            logger.error("[MANYCHAT] Error triggering flow: %s", e)
            return False

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
                field_value[:50] if field_value else "",
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
            result = await self.set_custom_field(subscriber_id, field_name, str(field_value))
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

    async def find_subscriber_by_custom_field(
        self,
        field_name: str,
        field_value: str,
    ) -> dict[str, Any] | None:
        """Find subscriber by custom field value.

        Args:
            field_name: Custom field name
            field_value: Value to search for

        Returns:
            Subscriber data or None
        """
        if not self.is_configured:
            return None

        client = await self._get_client()
        try:
            response = await client.post(
                "/subscriber/findByCustomField",
                json={
                    "field_name": field_name,
                    "field_value": field_value,
                },
            )
            response.raise_for_status()
            data = response.json()
            subscribers = data.get("data", [])
            return subscribers[0] if subscribers else None
        except Exception as e:
            logger.error("[MANYCHAT] Error finding subscriber: %s", e)
            return None


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_client: ManyChatClient | None = None


def get_manychat_client() -> ManyChatClient:
    """Get or create ManyChat API client singleton."""
    global _client
    if _client is None:
        _client = ManyChatClient()
    return _client


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


async def send_ai_response(
    subscriber_id: str,
    text: str,
    products: list[dict[str, Any]] | None = None,
    buttons: list[dict[str, str]] | None = None,
) -> bool:
    """Send AI agent response to ManyChat subscriber.
    
    This is the main function to call when sending AI responses back to users.
    
    Args:
        subscriber_id: ManyChat subscriber ID
        text: Response text
        products: Optional list of products to show as gallery
        buttons: Optional quick reply buttons
        
    Returns:
        True if successful
    """
    client = get_manychat_client()
    
    # Mark as AI responded
    await client.add_tag(subscriber_id, "ai_responded")
    
    # Send text with buttons if provided
    if buttons:
        await client.send_message_with_buttons(subscriber_id, text, buttons)
    else:
        await client.send_message(subscriber_id, text)
    
    # Send product gallery if provided
    if products:
        gallery_items = [
            {
                "title": p.get("name", "Товар"),
                "image_url": p.get("photo_url"),
                "subtitle": f"{p.get('price', 0)} грн",
                "buttons": [{"title": "Детальніше", "payload": f"product_{p.get('id', '')}"}],
            }
            for p in products[:10]
        ]
        await client.send_gallery(subscriber_id, gallery_items)
    
    return True


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
