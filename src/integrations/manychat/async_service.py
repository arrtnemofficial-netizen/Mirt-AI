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

import logging
import time
from typing import TYPE_CHECKING, Any

from src.agents import get_active_graph
from src.core.fallbacks import FallbackType, get_fallback_response
from src.core.rate_limiter import check_rate_limit
from src.services.conversation import create_conversation_handler
from src.services.debouncer import BufferedMessage, MessageDebouncer
from src.services.message_store import MessageStore, create_message_store
from src.services.renderer import render_agent_response_text

from .push_client import ManyChatPushClient, get_manychat_push_client
from .constants import (
    FIELD_AI_INTENT,
    FIELD_AI_STATE,
    FIELD_LAST_PRODUCT,
    FIELD_ORDER_SUM,
    TAG_AI_RESPONDED,
    TAG_NEEDS_HUMAN,
    TAG_ORDER_PAID,
    TAG_ORDER_STARTED,
)
from .response_builder import (
    build_manychat_field_values,
    build_manychat_messages,
    build_manychat_tags,
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
        *,
        user_id: str,
        text: str,
        image_url: str | None = None,
        channel: str = "instagram",
        subscriber_data: dict[str, Any] | None = None,
    ) -> None:
        """Process message and push response to ManyChat.
        
        This method is designed to be run in a background task.
        It handles debouncing, AI processing, and push delivery.
        
        Commands:
            /restart - Clear session and respond "Сесія очищена!"
            /start - Same as /restart (alias)
        
        Args:
            user_id: ManyChat subscriber ID
            text: Message text
            image_url: Optional image URL
            channel: Channel type (instagram, facebook, etc.)
        """
        start_time = time.time()
        logger.info("=" * 50)
        logger.info("[MANYCHAT:%s] 🔥 PROCESS_MESSAGE_ASYNC STARTED", user_id)
        logger.info("[MANYCHAT:%s]    text: '%s'", user_id, text[:100] if text else "(empty)")
        logger.info("[MANYCHAT:%s]    image_url: %s", user_id, image_url)
        logger.info("[MANYCHAT:%s]    channel: %s", user_id, channel)

        # RATE LIMITING: Захист від спаму/abuse
        if not check_rate_limit(user_id):
            logger.warning("[MANYCHAT:%s] ⚠️ RATE LIMITED - too many requests", user_id)
            fallback = get_fallback_response(FallbackType.RATE_LIMITED)
            await self.push_client.send_text(
                user_id, fallback["text"], channel=channel
            )
            return

        try:
            # Handle commands BEFORE debouncing
            raw_text = (text or "").strip()
            if raw_text.startswith(".;"):
                raw_text = raw_text[2:].lstrip()
            clean_text = raw_text.lower()
            first_token = clean_text.split(maxsplit=1)[0] if clean_text else ""
            if first_token in ("/restart", "/start", "restart", "start"):
                logger.info("[MANYCHAT:%s] 🔄 Detected RESTART command", user_id)
                await self._handle_restart_command(user_id, channel)
                return

            # Build metadata including username info
            extra_metadata = {}
            
            # Add image info
            if image_url:
                extra_metadata.update({
                    "has_image": True,
                    "image_url": image_url,
                })
                logger.info("[MANYCHAT:%s] 📷 Image URL set in metadata: %s", user_id, image_url[:80])
            else:
                logger.info("[MANYCHAT:%s] ⚠️ NO image_url provided", user_id)
            
            # Add username info from subscriber data
            if subscriber_data:
                # Instagram username
                instagram_username = subscriber_data.get("instagram_username") or subscriber_data.get("username")
                if instagram_username:
                    extra_metadata["instagram_username"] = instagram_username
                    logger.info("[MANYCHAT:%s] 📝 Instagram username: %s", user_id, instagram_username)
                
                # Name/nickname
                name = subscriber_data.get("name") or subscriber_data.get("full_name") or subscriber_data.get("first_name")
                if name:
                    extra_metadata["user_nickname"] = name
                    logger.info("[MANYCHAT:%s] 👤 User name: %s", user_id, name)

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

        # Keep async push behavior: include product images (better UX for push),
        # but keep logic centralized.
        messages = build_manychat_messages(agent_response, include_product_images=True)
        if any(m.get("type") == "image" for m in messages):
            logger.info("[MANYCHAT:%s] 📷 Including product images (%d total messages)", user_id, len(messages))

        # Build custom field values
        field_values = build_manychat_field_values(agent_response)

        # Build tags
        add_tags, remove_tags = build_manychat_tags(agent_response)

        # Build quick replies (currently disabled for Instagram sendContent API)
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

    async def _handle_restart_command(self, user_id: str, channel: str) -> None:
        """Handle /restart command - clear session and confirm."""
        # Delete session from store
        deleted = self.store.delete(user_id)

        if deleted:
            logger.info("[MANYCHAT:%s] 🔄 Session cleared via /restart", user_id)
            response_text = "Сесія очищена! ✨\nНапишіть мені що-небудь, і ми почнемо спочатку 💬"
        else:
            logger.info("[MANYCHAT:%s] 🔄 /restart called but no session existed", user_id)
            response_text = "Сесія очищена! ✨\nНапишіть мені що-небудь, щоб почати 💬"

        # Push confirmation
        await self.push_client.send_text(
            subscriber_id=user_id,
            text=response_text,
            channel=channel,
        )

    @staticmethod
    def _build_field_values(agent_response: AgentResponse) -> list[dict[str, Any]]:
        """Build Custom Field values from AgentResponse.
        
        Note: Values preserve their types (str, int, float) for ManyChat compatibility.
        ManyChat Number fields require numeric values, not strings.
        """
        return build_manychat_field_values(agent_response)

    @staticmethod
    def _build_tags(agent_response: AgentResponse) -> tuple[list[str], list[str]]:
        """Build tags to add/remove based on AgentResponse."""
        return build_manychat_tags(agent_response)

    @staticmethod
    def _build_quick_replies(agent_response: AgentResponse) -> list[dict[str, str]]:
        """Build Quick Reply buttons based on current state.
        
        NOTE: ManyChat sendContent API does NOT support quick_replies for Instagram.
        The 'type: text' format causes "Unsupported quick reply type" error.
        Returning empty list until proper format is determined.
        
        For now, users will type responses manually (which works fine).
        """
        # DISABLED: ManyChat sendContent rejects quick_replies with type='text'
        # TODO: Investigate proper format for Instagram quick replies via API
        return []


# Singleton
_async_service: ManyChatAsyncService | None = None


def get_manychat_async_service(store: SessionStore) -> ManyChatAsyncService:
    """Get or create async service instance."""
    global _async_service
    if _async_service is None:
        _async_service = ManyChatAsyncService(store)
    return _async_service
