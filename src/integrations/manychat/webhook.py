"""ManyChat webhook integration for Instagram DM flows.

This module handles ManyChat External Request webhooks and returns responses
in ManyChat v2 format with support for:
- Text messages and images
- Custom Field values (set_field_values)
- Tags (add/remove)
- Quick Replies
- Actions for flow automation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.agents import get_active_graph  # Fixed: was graph_v2
from src.services.conversation import create_conversation_handler
from src.services.debouncer import BufferedMessage, MessageDebouncer
from src.services.message_store import MessageStore, create_message_store

from .constants import (  # noqa: F401
    FIELD_AI_INTENT,
    FIELD_AI_STATE,
    FIELD_LAST_PRODUCT,
    TAG_AI_RESPONDED,
    TAG_NEEDS_HUMAN,
)
from .response_builder import (
    build_manychat_field_values,
    build_manychat_tags,
    build_manychat_v2_response,
)


if TYPE_CHECKING:
    from src.core.models import AgentResponse
    from src.services.session_store import SessionStore


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ManyChat Custom Field Names (повинні співпадати з твоїм ManyChat)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ManyChat Tags
# ---------------------------------------------------------------------------


class ManychatPayloadError(Exception):
    """Raised when payload does not contain required fields."""


class ManychatWebhook:
    """Processes ManyChat webhook payloads and returns response envelopes."""

    def __init__(
        self,
        store: SessionStore,
        runner=None,
        message_store: MessageStore | None = None,
    ) -> None:
        self.store = store
        self.runner = runner or get_active_graph()
        self.message_store = message_store or create_message_store()
        self._handler = create_conversation_handler(
            session_store=store,
            message_store=self.message_store,
            runner=self.runner,
        )
        # Initialize debouncer with 3.0 second delay for ManyChat
        # (Slightly longer than Telegram because webhooks can be slower)
        self.debouncer = MessageDebouncer(delay=3.0)

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Process a ManyChat webhook body and produce a response envelope."""
        user_id, text, image_url = self._extract_user_text_and_image(payload)

        # Build extra_metadata for images
        extra_metadata = {}
        if image_url:
            extra_metadata = {
                "has_image": True,
                "image_url": image_url,
            }
            logger.info("[MANYCHAT:%s] 📷 Image received: %s", user_id, image_url[:80])

        # ---------------------------------------------------------------------
        # DEBOUNCING LOGIC
        # ---------------------------------------------------------------------
        buffered_msg = BufferedMessage(
            text=text, has_image=bool(image_url), image_url=image_url, extra_metadata=extra_metadata
        )

        # Wait for aggregation.
        # Returns None if this request is superseded by a newer one.
        aggregated_msg = await self.debouncer.wait_for_debounce(user_id, buffered_msg)

        if aggregated_msg is None:
            # Superseded -> Return empty response ("silent success")
            logger.info("[MANYCHAT:%s] Request superseded by newer message, skipping.", user_id)
            return {
                "version": "v2",
                "content": {
                    "messages": [],
                    "actions": [],
                    "quick_replies": [],
                },
            }

        # ---------------------------------------------------------------------
        # PROCESS AGGREGATED MESSAGE
        # ---------------------------------------------------------------------
        final_text = aggregated_msg.text
        final_metadata = aggregated_msg.extra_metadata

        logger.info("[MANYCHAT:%s] Processing AGGREGATED: text='%s'", user_id, final_text[:50])

        # Use centralized handler with error handling
        result = await self._handler.process_message(
            user_id, final_text, extra_metadata=final_metadata
        )

        if result.is_fallback:
            logger.warning(
                "Fallback response for ManyChat user %s: %s",
                user_id,
                result.error,
            )

        return self._to_manychat_response(result.response)

    @staticmethod
    def _extract_user_text_and_image(payload: dict[str, Any]) -> tuple[str, str, str | None]:
        """Extract user ID, text, and optional image URL from ManyChat payload.

        ManyChat image formats:
        - message.attachments[].payload.url (Instagram images)
        - message.image (direct image URL)
        - data.image_url (custom field)
        """
        subscriber = payload.get("subscriber") or payload.get("user")
        message = payload.get("message") or payload.get("data", {}).get("message")

        text = None
        image_url = None

        if isinstance(message, dict):
            text = message.get("text") or message.get("content") or ""

            # Extract image from attachments (Instagram format)
            attachments = message.get("attachments", [])
            for attachment in attachments:
                if attachment.get("type") == "image":
                    payload_data = attachment.get("payload", {})
                    image_url = payload_data.get("url")
                    break

            # Fallback: direct image field
            if not image_url:
                image_url = message.get("image") or message.get("image_url")

        # Also check data.image_url (for custom ManyChat flows)
        if not image_url:
            data = payload.get("data", {})
            image_url = data.get("image_url") or data.get("photo_url")

        if not subscriber:
            raise ManychatPayloadError("Missing subscriber in payload")

        # Allow empty text if image is present
        if not text and not image_url:
            raise ManychatPayloadError("Missing message text or image in payload")

        user_id = str(subscriber.get("id") or subscriber.get("user_id") or "unknown")
        return user_id, text or "", image_url

    def _to_manychat_response(
        self,
        agent_response: AgentResponse,
    ) -> dict[str, Any]:
        """Map AgentResponse into ManyChat v2 compatible reply body.

        Returns a response with:
        - messages: Text and image content
        - set_field_values: Custom Fields to update
        - tags: Tags to add/remove
        - quick_replies: Quick reply buttons (optional)
        """
        # Add product images only для PHOTO_IDENT, щоб не дублювати фото в подальших стейтах
        include_product_images = agent_response.metadata.intent == "PHOTO_IDENT"

        # Build quick replies based on state
        quick_replies = self._build_quick_replies(agent_response)

        return build_manychat_v2_response(
            agent_response,
            include_product_images=include_product_images,
            quick_replies=quick_replies,
            include_debug=True,
        )

    @staticmethod
    def _build_field_values(
        agent_response: AgentResponse,
    ) -> list[dict[str, Any]]:
        """Build Custom Field values from AgentResponse.

        Note: Customer data (name, phone, city, NP) is now stored in session state
        by LLM and accessed via conversation.py, not parsed here.
        Values preserve their types (str, int, float) for ManyChat compatibility.
        """
        return build_manychat_field_values(agent_response)

    @staticmethod
    def _build_tags(agent_response: AgentResponse) -> tuple[list[str], list[str]]:
        """Build tags to add/remove based on AgentResponse."""
        return build_manychat_tags(agent_response)

    @staticmethod
    def _build_quick_replies(agent_response: AgentResponse) -> list[dict[str, str]]:
        """Build Quick Reply buttons based on current state."""
        current_state = agent_response.metadata.current_state
        replies: list[dict[str, str]] = []

        # State-specific quick replies
        if current_state in ("STATE_0_INIT", "STATE_1_DISCOVERY"):
            replies = [
                {"type": "text", "caption": "👗 Сукні"},
                {"type": "text", "caption": "👔 Костюми"},
                {"type": "text", "caption": "🧥 Тренчі"},
            ]
        elif current_state == "STATE_3_SIZE_COLOR":
            replies = [
                {"type": "text", "caption": "📏 Розмірна сітка"},
                {"type": "text", "caption": "🎨 Інші кольори"},
            ]
        elif current_state == "STATE_4_OFFER":
            replies = [
                {"type": "text", "caption": "✅ Беру!"},
                {"type": "text", "caption": "🎨 Інший колір"},
                {"type": "text", "caption": "📏 Інший розмір"},
            ]
        elif current_state == "STATE_5_PAYMENT_DELIVERY":
            replies = [
                {"type": "text", "caption": "💳 Повна оплата"},
                {"type": "text", "caption": "💵 Передплата 200 грн"},
            ]

        # Always add manager button for complex cases
        if agent_response.metadata.escalation_level != "NONE":
            replies = [{"type": "text", "caption": "👩 Зв'язок з менеджером"}]

        return replies
