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
import time
import uuid
from typing import TYPE_CHECKING, Any

from src.agents import get_active_graph
from src.conf.config import settings
from src.core.fallbacks import FallbackType, get_fallback_response
from src.core.rate_limiter import check_rate_limit
from src.services.conversation import create_conversation_handler
from src.services.debouncer import BufferedMessage, MessageDebouncer
from src.services.message_store import MessageStore, create_message_store
from src.services.renderer import render_agent_response_text
from src.core.logging import classify_root_cause, log_event, safe_preview

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
        # Debouncer: aggregate rapid messages
        self.debouncer = MessageDebouncer(delay=float(getattr(settings, "MANYCHAT_DEBOUNCE_SECONDS", 1.0)))

    async def _safe_send_text(
        self,
        *,
        subscriber_id: str,
        text: str,
        channel: str,
        trace_id: str | None = None,
    ) -> bool:
        try:
            return await self.push_client.send_text(
                subscriber_id=subscriber_id,
                text=text,
                channel=channel,
                trace_id=trace_id,
            )
        except TypeError:
            return await self.push_client.send_text(
                subscriber_id=subscriber_id,
                text=text,
                channel=channel,
            )

    async def _safe_send_content(
        self,
        *,
        subscriber_id: str,
        messages: list[dict[str, Any]],
        channel: str,
        quick_replies: list[dict[str, str]] | None,
        set_field_values: list[dict[str, Any]] | None,
        add_tags: list[str] | None,
        remove_tags: list[str] | None,
        trace_id: str | None = None,
    ) -> bool:
        try:
            return await self.push_client.send_content(
                subscriber_id=subscriber_id,
                messages=messages,
                channel=channel,
                quick_replies=quick_replies,
                set_field_values=set_field_values,
                add_tags=add_tags,
                remove_tags=remove_tags,
                trace_id=trace_id,
            )
        except TypeError:
            return await self.push_client.send_content(
                subscriber_id=subscriber_id,
                messages=messages,
                channel=channel,
                quick_replies=quick_replies,
                set_field_values=set_field_values,
                add_tags=add_tags,
                remove_tags=remove_tags,
            )

    async def _maybe_push_interim(
        self,
        *,
        user_id: str,
        channel: str,
        trace_id: str,
        has_image: bool,
    ) -> None:
        """Push a short interim message if processing is taking too long."""
        try:
            fallback_after = float(getattr(settings, "MANYCHAT_FALLBACK_AFTER_SECONDS", 10.0))
        except Exception:
            fallback_after = 10.0

        if fallback_after <= 0:
            return

        await asyncio.sleep(fallback_after)

        # If we reached here, main processing likely still running.
        # Keep it short: 1 bubble, no images.
        interim_text = str(
            getattr(
                settings,
                "MANYCHAT_INTERIM_TEXT_WITH_IMAGE" if has_image else "MANYCHAT_INTERIM_TEXT",
                "Секунду, уточняю по наявності та деталях.",
            )
            or ""
        ).strip()

        if not interim_text:
            return
        await self._safe_send_text(
            subscriber_id=user_id,
            text=interim_text,
            channel=channel,
            trace_id=trace_id,
        )

    async def process_message_async(
        self,
        *,
        user_id: str,
        text: str,
        image_url: str | None = None,
        channel: str = "instagram",
        subscriber_data: dict[str, Any] | None = None,
        trace_id: str | None = None,
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
        trace_id = trace_id or str(uuid.uuid4())
        log_event(
            logger,
            event="manychat_process_start",
            trace_id=trace_id,
            user_id=user_id,
            channel=channel,
            text_len=len(text or ""),
            text_preview=safe_preview(text, 160),
            has_image=bool(image_url),
            image_url_preview=safe_preview(image_url, 100),
        )

        # RATE LIMITING: Захист від спаму/abuse
        if not check_rate_limit(user_id):
            log_event(
                logger,
                event="manychat_rate_limited",
                level="warning",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
            )
            fallback = get_fallback_response(FallbackType.RATE_LIMITED)
            await self._safe_send_text(
                subscriber_id=user_id,
                text=str(fallback["text"]),
                channel=channel,
                trace_id=trace_id,
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
                log_event(
                    logger,
                    event="manychat_restart_command",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                )
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
                log_event(
                    logger,
                    event="manychat_image_attached",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                    has_image=True,
                    image_url_preview=safe_preview(image_url, 100),
                )
            
            # Add username info from subscriber data
            if subscriber_data:
                # Instagram username
                instagram_username = subscriber_data.get("instagram_username") or subscriber_data.get("username")
                if instagram_username:
                    extra_metadata["instagram_username"] = instagram_username
                    log_event(
                        logger,
                        event="manychat_subscriber_username",
                        trace_id=trace_id,
                        user_id=user_id,
                        channel=channel,
                    )
                
                # Name/nickname
                name = subscriber_data.get("name") or subscriber_data.get("full_name") or subscriber_data.get("first_name")
                if name:
                    extra_metadata["user_nickname"] = name
                    log_event(
                        logger,
                        event="manychat_subscriber_name",
                        trace_id=trace_id,
                        user_id=user_id,
                        channel=channel,
                    )

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
                log_event(
                    logger,
                    event="manychat_debounce_superseded",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                )
                return

            final_text = aggregated_msg.text
            final_metadata = aggregated_msg.extra_metadata

            # Prefer debouncer flag; fallback to metadata for test stubs/mocks.
            has_image_final = bool(getattr(aggregated_msg, "has_image", False))
            if not has_image_final and isinstance(final_metadata, dict):
                has_image_final = bool(final_metadata.get("has_image"))

            # Enforce time budget per message. Also push an interim message if we exceed a smaller threshold.
            # Vision processing can take 20-30 seconds, so we need a larger budget
            try:
                text_budget = float(getattr(settings, "MANYCHAT_TEXT_TIME_BUDGET_SECONDS", 25.0))
                vision_budget = float(getattr(settings, "MANYCHAT_VISION_TIME_BUDGET_SECONDS", 55.0))
            except Exception:
                text_budget, vision_budget = 25.0, 55.0
            time_budget = vision_budget if has_image_final else text_budget

            interim_task = asyncio.create_task(
                self._maybe_push_interim(
                    user_id=user_id,
                    channel=channel,
                    trace_id=trace_id,
                    has_image=has_image_final,
                )
            )

            log_event(
                logger,
                event="manychat_debounce_aggregated",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
                text_len=len(final_text or ""),
                text_preview=safe_preview(final_text, 160),
                has_image=has_image_final,
            )

            # Process through conversation handler with timeout.
            if isinstance(final_metadata, dict):
                final_metadata = {**final_metadata, "trace_id": trace_id, "channel": channel}

            try:
                result = await asyncio.wait_for(
                    self._handler.process_message(
                        user_id,
                        final_text,
                        extra_metadata=final_metadata,
                    ),
                    timeout=max(time_budget, 1.0),
                )
            except asyncio.TimeoutError:
                log_event(
                    logger,
                    event="manychat_time_budget_exceeded",
                    level="warning",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                    budget_seconds=time_budget,
                    has_image=has_image_final,
                )

                fallback = get_fallback_response(FallbackType.LLM_TIMEOUT)
                if fallback.get("text"):
                    await self._safe_send_text(
                        subscriber_id=user_id,
                        text=str(fallback["text"]),
                        channel=channel,
                        trace_id=trace_id,
                    )
                return
            finally:
                # Stop interim task if main processing finished or timed out.
                interim_task.cancel()

            if result.is_fallback:
                root_cause = classify_root_cause(
                    result.error,
                    current_state=getattr(result.response.metadata, "current_state", None),
                    intent=getattr(result.response.metadata, "intent", None),
                    channel=channel,
                )
                log_event(
                    logger,
                    event="manychat_fallback_triggered",
                    level="warning",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                    root_cause=root_cause,
                    error=safe_preview(result.error, 200),
                )

            # Push response to ManyChat
            await self._push_response(user_id, result.response, channel, trace_id=trace_id)

            log_event(
                logger,
                event="manychat_process_done",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
                latency_ms=round((time.time() - start_time) * 1000, 2),
                intent=getattr(result.response.metadata, "intent", None),
                current_state=getattr(result.response.metadata, "current_state", None),
                messages_count=len(getattr(result.response, "messages", []) or []),
                products_count=len(getattr(result.response, "products", []) or []),
            )

        except Exception as e:
            root_cause = classify_root_cause(e, channel=channel)
            log_event(
                logger,
                event="manychat_processing_error",
                level="exception",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
                root_cause=root_cause,
                error_type=type(e).__name__,
                error=safe_preview(e, 200),
            )
            # Try to send error message
            await self._push_error_message(user_id, channel, trace_id=trace_id)

    async def _push_response(
        self,
        user_id: str,
        agent_response: AgentResponse,
        channel: str,
        *,
        trace_id: str | None = None,
    ) -> None:
        """Convert AgentResponse to ManyChat format and push."""

        # Keep async push behavior: include product images (better UX for push),
        # but keep logic centralized.
        messages = build_manychat_messages(agent_response, include_product_images=True)
        if any(m.get("type") == "image" for m in messages):
            log_event(
                logger,
                event="manychat_including_images",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
                messages_count=len(messages),
            )

        # Build custom field values
        field_values = build_manychat_field_values(agent_response)

        # Build tags
        add_tags, remove_tags = build_manychat_tags(agent_response)

        # Build quick replies (currently disabled for Instagram sendContent API)
        quick_replies = self._build_quick_replies(agent_response)

        # Push to ManyChat
        log_event(
            logger,
            event="manychat_push_attempt",
            trace_id=trace_id,
            user_id=user_id,
            channel=channel,
            messages_count=len(messages),
        )

        success = await self._safe_send_content(
            subscriber_id=user_id,
            messages=messages,
            channel=channel,
            quick_replies=quick_replies,
            set_field_values=field_values,
            add_tags=add_tags,
            remove_tags=remove_tags,
            trace_id=trace_id,
        )

        if success:
            log_event(
                logger,
                event="manychat_push_ok",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
                messages_count=len(messages),
                current_state=agent_response.metadata.current_state,
                intent=agent_response.metadata.intent,
                escalation_level=agent_response.metadata.escalation_level,
            )
        else:
            log_event(
                logger,
                event="manychat_push_failed",
                level="error",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
            )

    @staticmethod
    def _get_error_text() -> str:
        """Get human-like error message."""
        from src.core.human_responses import get_human_response
        return get_human_response("error")

    async def _push_error_message(self, user_id: str, channel: str, *, trace_id: str) -> None:
        """Push a friendly error message."""
        await self._safe_send_text(
            subscriber_id=user_id,
            text=self._get_error_text(),
            channel=channel,
            trace_id=trace_id,
        )


    async def _handle_restart_command(self, user_id: str, channel: str) -> None:
        """Handle /restart command - clear session and confirm."""
        import time as _time
        _restart_start = _time.time()

        # Clear any pending debouncer buffers/timers so no stale aggregated message
        # is processed after restart.
        try:
            self.debouncer.clear_session(user_id)
        except Exception:
            logger.debug("[MANYCHAT:%s] Failed to clear debouncer session", user_id, exc_info=True)

        # CRITICAL: Also reset LangGraph checkpointer state for this thread.
        # Otherwise, persistent checkpointers (Postgres) will restore an old dialog_phase
        # (e.g., WAITING_FOR_PAYMENT_PROOF) even after SessionStore is cleared.
        # NOTE: This is OPTIONAL - skip if it takes too long (>5 sec timeout)
        try:
            from src.agents.langgraph.state import create_initial_state

            reset_state = create_initial_state(
                session_id=user_id,
                metadata={"channel": channel},
            )
            _lg_start = _time.time()
            # Use timeout to prevent blocking - checkpointer reset is optional
            await asyncio.wait_for(
                self.runner.aupdate_state(
                    {"configurable": {"thread_id": user_id}},
                    reset_state,
                ),
                timeout=5.0,  # Max 5 seconds for checkpointer reset
            )
            logger.info(
                "[MANYCHAT:%s] LangGraph state reset via /restart (%.2fs)",
                user_id,
                _time.time() - _lg_start,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[MANYCHAT:%s] LangGraph state reset timed out (>5s), skipping",
                user_id,
            )
        except Exception:
            logger.debug(
                "[MANYCHAT:%s] Failed to reset LangGraph state via /restart",
                user_id,
                exc_info=True,
            )

        # Delete session from store
        # CRITICAL: Use to_thread() to avoid blocking event loop!
        _del_start = _time.time()
        deleted = await asyncio.to_thread(self.store.delete, user_id)
        logger.info("[MANYCHAT:%s] store.delete took %.2fs", user_id, _time.time() - _del_start)

        if deleted:
            logger.info("[MANYCHAT:%s] Session cleared via /restart", user_id)
            response_text = (
                "Сесія очищена. Можемо почати спочатку. Напишіть, що вас цікавить 😊"
            )
        else:
            logger.info("[MANYCHAT:%s] /restart called but no session existed", user_id)
            response_text = (
                "Сесія вже була порожня. Напишіть, що вас цікавить 😊"
            )

        # Push confirmation
        await self._safe_send_text(
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
