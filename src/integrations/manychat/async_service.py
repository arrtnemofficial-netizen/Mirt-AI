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
from src.core.logging import classify_root_cause, log_event, safe_preview
from src.core.rate_limiter import check_rate_limit
from src.services.conversation import create_conversation_handler
from src.services.debouncer import MessageDebouncer
from src.services.media_utils import normalize_image_url
from src.services.message_store import MessageStore, create_message_store

from .pipeline import process_manychat_pipeline
from .push_client import ManyChatPushClient, get_manychat_push_client
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
        self._restart_inflight: set[str] = set()
        self._handler = create_conversation_handler(
            session_store=store,
            message_store=self.message_store,
            runner=self.runner,
        )
        # Debouncer: aggregate rapid messages
        self.debouncer = MessageDebouncer(
            delay=float(getattr(settings, "MANYCHAT_DEBOUNCE_SECONDS", 1.0))
        )

    @staticmethod
    def _normalize_command_text(text: str) -> tuple[str, str, str]:
        raw_text = (text or "").strip()
        if raw_text.startswith(".;"):
            raw_text = raw_text[2:].lstrip()
        clean_text = raw_text.lower()
        first_token = clean_text.split(maxsplit=1)[0] if clean_text else ""
        return raw_text, clean_text, first_token

    @staticmethod
    def _is_restart_command(first_token: str) -> bool:
        return first_token == "/restart"

    def _log_process_start(
        self,
        *,
        trace_id: str,
        user_id: str,
        channel: str,
        text: str,
        image_url: str | None,
    ) -> None:
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

    def _log_process_done(
        self,
        *,
        trace_id: str,
        user_id: str,
        channel: str,
        start_time: float,
        response: AgentResponse,
    ) -> None:
        log_event(
            logger,
            event="manychat_process_done",
            trace_id=trace_id,
            user_id=user_id,
            channel=channel,
            latency_ms=round((time.time() - start_time) * 1000, 2),
            intent=getattr(response.metadata, "intent", None),
            current_state=getattr(response.metadata, "current_state", None),
            messages_count=len(getattr(response, "messages", []) or []),
            products_count=len(getattr(response, "products", []) or []),
        )

    def _build_extra_metadata(
        self,
        *,
        user_id: str,
        channel: str,
        image_url: str | None,
        subscriber_data: dict[str, Any] | None,
        trace_id: str,
    ) -> dict[str, Any]:
        extra_metadata: dict[str, Any] = {}

        if image_url:
            extra_metadata.update({"has_image": True, "image_url": image_url})
            log_event(
                logger,
                event="manychat_image_attached",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
                has_image=True,
                image_url_preview=safe_preview(image_url, 100),
            )

        if subscriber_data:
            instagram_username = subscriber_data.get("instagram_username") or subscriber_data.get(
                "username"
            )
            if instagram_username:
                extra_metadata["instagram_username"] = instagram_username
                log_event(
                    logger,
                    event="manychat_subscriber_username",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                )

            name = (
                subscriber_data.get("name")
                or subscriber_data.get("full_name")
                or subscriber_data.get("first_name")
            )
            if name:
                extra_metadata["user_nickname"] = name
                log_event(
                    logger,
                    event="manychat_subscriber_name",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                )

        return extra_metadata

    @staticmethod
    def _get_time_budget(has_image: bool) -> float:
        try:
            text_budget = float(getattr(settings, "MANYCHAT_TEXT_TIME_BUDGET_SECONDS", 25.0))
            vision_budget = float(getattr(settings, "MANYCHAT_VISION_TIME_BUDGET_SECONDS", 55.0))
        except Exception:
            text_budget, vision_budget = 25.0, 55.0
        return vision_budget if has_image else text_budget

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

        Args:
            user_id: ManyChat subscriber ID
            text: Message text
            image_url: Optional image URL
            channel: Channel type (instagram, facebook, etc.)
        """
        start_time = time.time()
        trace_id = trace_id or str(uuid.uuid4())
        image_url = normalize_image_url(image_url)
        self._log_process_start(
            trace_id=trace_id,
            user_id=user_id,
            channel=channel,
            text=text,
            image_url=image_url,
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
            _, _, first_token = self._normalize_command_text(text)
            if self._is_restart_command(first_token):
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
            extra_metadata = self._build_extra_metadata(
                user_id=user_id,
                channel=channel,
                image_url=image_url,
                subscriber_data=subscriber_data,
                trace_id=trace_id,
            )
            extra_metadata = {**extra_metadata, "trace_id": trace_id, "channel": channel}

            interim_task: asyncio.Task[None] | None = None
            has_image_final: bool | None = None
            time_budget: float | None = None

            def _on_superseded() -> None:
                log_event(
                    logger,
                    event="manychat_debounce_superseded",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                )

            def _on_debounced(
                _aggregated_msg: Any,
                has_image: bool,
                final_text: str,
                _final_metadata: dict[str, Any] | None,
            ) -> None:
                nonlocal interim_task, has_image_final, time_budget
                has_image_final = has_image
                time_budget = self._get_time_budget(has_image)
                interim_task = asyncio.create_task(
                    self._maybe_push_interim(
                        user_id=user_id,
                        channel=channel,
                        trace_id=trace_id,
                        has_image=has_image,
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
                    has_image=has_image,
                )

            try:
                pipeline_result = await process_manychat_pipeline(
                    handler=self._handler,
                    debouncer=self.debouncer,
                    user_id=user_id,
                    text=text,
                    image_url=image_url,
                    extra_metadata=extra_metadata,
                    time_budget_provider=self._get_time_budget,
                    on_superseded=_on_superseded,
                    on_debounced=_on_debounced,
                )
                if pipeline_result is None:
                    return
            except TimeoutError:
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
                if interim_task:
                    interim_task.cancel()

            result = pipeline_result.result

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

            self._log_process_done(
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
                start_time=start_time,
                response=result.response,
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
        if user_id in self._restart_inflight:
            logger.info("[MANYCHAT:%s] /restart already in progress", user_id)
            await self._safe_send_text(
                subscriber_id=user_id,
                text="Сесія очищується. Напишіть, будь ласка, запит ще раз 🙂",
                channel=channel,
            )
            return

        self._restart_inflight.add(user_id)
        try:
            # Clear any pending debouncer buffers/timers so no stale aggregated message
            # is processed after restart.
            try:
                self.debouncer.clear_session(user_id)
            except Exception:
                logger.debug(
                    "[MANYCHAT:%s] Failed to clear debouncer session", user_id, exc_info=True
                )

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
            except TimeoutError:
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
            logger.info(
                "[MANYCHAT:%s] store.delete took %.2fs",
                user_id,
                _time.time() - _del_start,
            )

            # Clear message history for this session (idempotent).
            try:
                await asyncio.to_thread(self.message_store.delete, user_id)
            except Exception:
                logger.debug(
                    "[MANYCHAT:%s] Failed to clear message store via /restart",
                    user_id,
                    exc_info=True,
                )

            if deleted:
                logger.info("[MANYCHAT:%s] Session cleared via /restart", user_id)
                response_text = (
                    "Сесія очищена. Розкажіть, будь ласка, що саме вас цікавить 🙂"
                )
            else:
                logger.info("[MANYCHAT:%s] /restart called but no session existed", user_id)
                response_text = (
                    "Сесія вже була очищена. Напишіть, будь ласка, що саме вас цікавить 🙂"
                )

            # Push confirmation
            await self._safe_send_text(
                subscriber_id=user_id,
                text=response_text,
                channel=channel,
            )
        finally:
            self._restart_inflight.discard(user_id)

    @staticmethod
    def _build_quick_replies(_agent_response: AgentResponse) -> list[dict[str, str]]:
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
