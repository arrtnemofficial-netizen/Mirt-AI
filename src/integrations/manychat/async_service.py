"""ManyChat Async Service - processes messages and pushes responses.

This service combines:
1. WizaLive architecture (async push, no timeout)
2. MIRT features (debouncing, images, custom fields, tags, quick replies)

Flow:
1. Webhook receives message → returns 202 Accepted immediately
2. Background task processes message through LangGraph
3. Response pushed to ManyChat via API
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from src.agents import get_active_graph
from src.services.conversation import create_conversation_handler
from src.services.debouncer import BufferedMessage, MessageDebouncer
from src.services.message_store import MessageStore, create_message_store
from src.services.renderer import render_agent_response_text

from .push_client import ManyChatPushClient, get_manychat_push_client
from .webhook import (
    FIELD_AI_INTENT,
    FIELD_AI_STATE,
    FIELD_LAST_PRODUCT,
    FIELD_ORDER_SUM,
    TAG_AI_RESPONDED,
    TAG_NEEDS_HUMAN,
    TAG_ORDER_PAID,
    TAG_ORDER_STARTED,
)


if TYPE_CHECKING:
    from src.core.models import AgentResponse
    from src.services.session_store import SessionStore


logger = logging.getLogger(__name__)


class ManyChatAsyncService:
    """Async push-based ManyChat service with all MIRT features."""

    def __init__(
        self,
        store: SessionStore,
        runner=None,
        message_store: MessageStore | None = None,
        push_client: ManyChatPushClient | None = None,
    ) -> None:
        self.store = store
        self.runner = runner or get_active_graph()
        self.message_store = message_store or create_message_store()
        self.push_client = push_client or get_manychat_push_client()
        self._handler = create_conversation_handler(
            session_store=store,
            message_store=self.message_store,
            runner=self.runner,
        )
        # Debouncer: wait 3 seconds to aggregate rapid messages
        self.debouncer = MessageDebouncer(delay=3.0)

    async def process_message_async(
        self,
        user_id: str,
        text: str,
        image_url: str | None = None,
        channel: str = "instagram",
    ) -> None:
        """Process message and push response to ManyChat.
        
        This method is designed to be run in a background task.
        It handles debouncing, AI processing, and push delivery.
        
        Args:
            user_id: ManyChat subscriber ID
            text: Message text
            image_url: Optional image URL
            channel: Channel type (instagram, facebook, etc.)
        """
        try:
            # Build metadata for images
            extra_metadata = {}
            if image_url:
                extra_metadata = {
                    "has_image": True,
                    "image_url": image_url,
                }
                logger.info("[MANYCHAT:%s] 📷 Image received: %s", user_id, image_url[:80])

            # Debouncing: aggregate rapid messages
            buffered_msg = BufferedMessage(
                text=text,
                has_image=bool(image_url),
                image_url=image_url,
                extra_metadata=extra_metadata,
            )

            aggregated_msg = await self.debouncer.wait_for_debounce(user_id, buffered_msg)

            if aggregated_msg is None:
                # Superseded by newer message
                logger.info("[MANYCHAT:%s] Request superseded, skipping", user_id)
                return

            final_text = aggregated_msg.text
            final_metadata = aggregated_msg.extra_metadata

            logger.info(
                "[MANYCHAT:%s] Processing AGGREGATED: text='%s'",
                user_id,
                final_text[:50] if final_text else "(empty)",
            )

            # Process through conversation handler
            result = await self._handler.process_message(
                user_id,
                final_text,
                extra_metadata=final_metadata,
            )

            if result.is_fallback:
                logger.warning(
                    "[MANYCHAT:%s] Fallback response: %s",
                    user_id,
                    result.error,
                )

            # Push response to ManyChat
            await self._push_response(user_id, result.response, channel)

        except Exception as e:
            logger.exception("[MANYCHAT:%s] Processing error: %s", user_id, e)
            # Try to send error message
            await self._push_error_message(user_id, channel)

    async def _push_response(
        self,
        user_id: str,
        agent_response: AgentResponse,
        channel: str,
    ) -> None:
        """Convert AgentResponse to ManyChat format and push."""
        
        # Build messages
        text_chunks = render_agent_response_text(agent_response)
        messages: list[dict[str, Any]] = [
            {"type": "text", "text": chunk} for chunk in text_chunks
        ]

        # Add product images for PHOTO_IDENT
        if agent_response.metadata.intent == "PHOTO_IDENT":
            for product in agent_response.products:
                if product.photo_url:
                    messages.append({
                        "type": "image",
                        "url": product.photo_url,
                        "caption": "",
                    })

        # Build custom field values
        field_values = self._build_field_values(agent_response)

        # Build tags
        add_tags, remove_tags = self._build_tags(agent_response)

        # Build quick replies
        quick_replies = self._build_quick_replies(agent_response)

        # Push to ManyChat
        success = await self.push_client.send_content(
            subscriber_id=user_id,
            messages=messages,
            channel=channel,
            quick_replies=quick_replies,
            set_field_values=field_values,
            add_tags=add_tags,
            remove_tags=remove_tags,
        )

        if success:
            logger.info(
                "[MANYCHAT:%s] ✅ Response pushed: %d messages, state=%s",
                user_id,
                len(messages),
                agent_response.metadata.current_state,
            )
        else:
            logger.error("[MANYCHAT:%s] ❌ Failed to push response", user_id)

    @staticmethod
    def _get_error_text() -> str:
        """Get human-like error message."""
        from src.core.human_responses import get_human_response
        return get_human_response("error")

    async def _push_error_message(self, user_id: str, channel: str) -> None:
        """Push a friendly error message."""
        await self.push_client.send_text(
            subscriber_id=user_id,
            text=self._get_error_text(),
            channel=channel,
        )

    @staticmethod
    def _build_field_values(agent_response: AgentResponse) -> list[dict[str, str]]:
        """Build Custom Field values from AgentResponse."""
        fields = [
            {"field_name": FIELD_AI_STATE, "field_value": agent_response.metadata.current_state},
            {"field_name": FIELD_AI_INTENT, "field_value": agent_response.metadata.intent},
        ]

        if agent_response.products:
            last_product = agent_response.products[-1]
            fields.append({"field_name": FIELD_LAST_PRODUCT, "field_value": last_product.name})
            if last_product.price:
                fields.append({"field_name": FIELD_ORDER_SUM, "field_value": str(last_product.price)})

        return fields

    @staticmethod
    def _build_tags(agent_response: AgentResponse) -> tuple[list[str], list[str]]:
        """Build tags to add/remove based on AgentResponse."""
        add_tags = [TAG_AI_RESPONDED]
        remove_tags: list[str] = []

        if agent_response.metadata.escalation_level != "NONE":
            add_tags.append(TAG_NEEDS_HUMAN)
        else:
            remove_tags.append(TAG_NEEDS_HUMAN)

        current_state = agent_response.metadata.current_state
        if current_state in ("STATE_5_PAYMENT_DELIVERY", "STATE_6_UPSELL"):
            add_tags.append(TAG_ORDER_STARTED)

        if current_state == "STATE_7_END" and agent_response.event == "escalation":
            if agent_response.escalation and "ORDER_CONFIRMED" in (
                agent_response.escalation.reason or ""
            ):
                add_tags.append(TAG_ORDER_PAID)

        return add_tags, remove_tags

    @staticmethod
    def _build_quick_replies(agent_response: AgentResponse) -> list[dict[str, str]]:
        """Build Quick Reply buttons based on current state."""
        current_state = agent_response.metadata.current_state
        replies: list[dict[str, str]] = []

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

        if agent_response.metadata.escalation_level != "NONE":
            replies = [{"type": "text", "caption": "👩 Зв'язок з менеджером"}]

        return replies


# Singleton
_async_service: ManyChatAsyncService | None = None


def get_manychat_async_service(store: SessionStore) -> ManyChatAsyncService:
    """Get or create async service instance."""
    global _async_service
    if _async_service is None:
        _async_service = ManyChatAsyncService(store)
    return _async_service
