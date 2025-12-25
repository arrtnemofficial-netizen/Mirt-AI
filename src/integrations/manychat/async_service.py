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
from src.core.human_responses import get_human_response
from src.core.logging import log_event, safe_preview
from src.core.rate_limiter import check_rate_limit
from src.services.client_data_parser import parse_client_data
from src.services.conversation import create_conversation_handler
from src.services.infra.debouncer import create_debouncer
from src.services.infra.media_utils import normalize_image_url
from src.services.infra.message_store import MessageStore, create_message_store

from .pipeline import process_manychat_pipeline
from .push_client import ManyChatPushClient, get_manychat_push_client
from .response_builder import (
    build_manychat_field_values,
    build_manychat_messages,
    build_manychat_response,
    build_manychat_tags,
    build_text_response,
)
from .service_utils import (
    build_extra_metadata,
    get_time_budget,
    handle_restart_command,
    maybe_push_interim,
    safe_send_content,
    safe_send_text,
)


if TYPE_CHECKING:
    from src.core.models import AgentResponse
    from src.services.infra.session_store import SessionStore


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
        active_runner = runner or get_active_graph()
        
        # Validate runner is not None
        if active_runner is None:
            logger.error(
                "ManyChatAsyncService.__init__: get_active_graph() returned None. "
                "Graph was not initialized properly."
            )
            raise ValueError(
                "Runner cannot be None. Graph must be initialized before creating ManyChatAsyncService. "
                "Check that get_active_graph() returns a valid runner."
            )
        
        self.runner = active_runner
        self.message_store = message_store or create_message_store()
        self.push_client = push_client or get_manychat_push_client()
        self._restart_inflight: set[str] = set()
        self._handler = create_conversation_handler(
            session_store=store,
            message_store=self.message_store,
            runner=self.runner,
        )
        # Debouncer: aggregate rapid messages (uses Redis if available for multi-instance)
        self.debouncer = create_debouncer(
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
            /restart - Clear session and respond "\u0421\u0435\u0441\u0456\u044f \u043e\u0447\u0438\u0449\u0435\u043d\u0430!"

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
            await safe_send_text(
                self.push_client,
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
                if user_id in self._restart_inflight:
                    logger.info("[MANYCHAT:%s] /restart already in progress", user_id)
                    await safe_send_text(
                        self.push_client,
                        subscriber_id=user_id,
                        text="Сесія очищується. Напишіть, будь ласка, запит ще раз 🙂",
                        channel=channel,
                    )
                    return
                self._restart_inflight.add(user_id)
                try:
                    await handle_restart_command(
                        user_id=user_id,
                        channel=channel,
                        runner=self.runner,
                        store=self.store,
                        debouncer=self.debouncer,
                        push_client=self.push_client,
                        logger=logger,
                    )
                finally:
                    self._restart_inflight.discard(user_id)
                return

            # Build metadata including username info
            extra_metadata = build_extra_metadata(
                user_id=user_id,
                channel=channel,
                image_url=image_url,
                subscriber_data=subscriber_data,
                trace_id=trace_id,
                logger=logger,
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
                time_budget = get_time_budget(has_image)
                interim_task = asyncio.create_task(
                    maybe_push_interim(
                        self.push_client,
                        user_id=user_id,
                        channel=channel,
                        trace_id=trace_id,
                        has_image=has_image,
                        logger=logger,
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
                    time_budget_provider=get_time_budget,
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
                    await safe_send_text(
                        self.push_client,
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
                log_event(
                    logger,
                    event="manychat_fallback_triggered",
                    level="warning",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                    error=safe_preview(result.error, 200),
                    intent=getattr(result.response.metadata, "intent", None),
                    current_state=getattr(result.response.metadata, "current_state", None),
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
            log_event(
                logger,
                event="manychat_processing_error",
                level="exception",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
                error_type=type(e).__name__,
                error=safe_preview(e, 200),
            )
            # Try to send error message
            await safe_send_text(
                self.push_client,
                subscriber_id=user_id,
                text=get_human_response("error"),
                channel=channel,
                trace_id=trace_id,
            )

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

        success = await safe_send_content(
            self.push_client,
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

    async def process_message_sync(
        self,
        *,
        user_id: str,
        text: str,
        image_url: str | None = None,
        channel: str = "instagram",
        subscriber_data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Process message inline and return ManyChat response (sync mode)."""
        trace_id = trace_id or str(uuid.uuid4())
        image_url = normalize_image_url(image_url)

        # Build metadata
        extra_metadata = build_extra_metadata(
            user_id=user_id,
            channel=channel,
            image_url=image_url,
            subscriber_data=subscriber_data,
            trace_id=trace_id,
            logger=logger,
        )
        extra_metadata = {**extra_metadata, "trace_id": trace_id, "channel": channel}

        pipeline_result = await process_manychat_pipeline(
            handler=self._handler,
            debouncer=self.debouncer,
            user_id=user_id,
            text=text or "",
            image_url=image_url,
            extra_metadata=extra_metadata,
            time_budget_provider=get_time_budget,
        )
        if pipeline_result is None:
            return build_text_response("")

        result = pipeline_result.result
        if result.is_fallback:
            log_event(
                logger,
                event="manychat_fallback_triggered_sync",
                level="warning",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
                error=safe_preview(result.error, 200),
                intent=getattr(result.response.metadata, "intent", None),
                current_state=getattr(result.response.metadata, "current_state", None),
            )

        # Parse client data (non-critical, so wrap in try-except)
        try:
            if settings.DEBUG_TRACE_LOGS:
                log_event(
                    logger,
                    event="parse_client_data_entry",
                    level="debug",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                    text_len=len(text or ""),
                    text_preview=safe_preview(text, 120),
                )

            client_data = parse_client_data(text or "")

            if settings.DEBUG_TRACE_LOGS:
                log_event(
                    logger,
                    event="parse_client_data_success",
                    level="debug",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                    has_phone=bool(getattr(client_data, "phone", None)),
                    has_name=bool(getattr(client_data, "full_name", None)),
                )
        except Exception as parse_error:
            if settings.DEBUG_TRACE_LOGS:
                log_event(
                    logger,
                    event="parse_client_data_error",
                    level="warning",
                    trace_id=trace_id,
                    user_id=user_id,
                    channel=channel,
                    error_type=type(parse_error).__name__,
                    error=safe_preview(str(parse_error), 200),
                    text_len=len(text or ""),
                )
            logger.warning(
                "Failed to parse client data from text (len=%d): %s",
                len(text or ""),
                str(parse_error)[:200],
            )
            # Use empty client data if parsing fails
            from src.services.client_data_parser import ClientData
            client_data = ClientData()
        
        return build_manychat_response(result.response, client_data=client_data)

    @staticmethod
    def _build_quick_replies(_agent_response: AgentResponse) -> list[dict[str, str]]:
        """Build Quick Reply buttons based on current state.

        NOTE: ManyChat sendContent API does NOT support quick_replies for Instagram.
        The 'type: text' format causes "Unsupported quick reply type" error.

        For now, users will type responses manually (which works fine).
        """
        # DISABLED: ManyChat sendContent rejects quick_replies with type='text'
        # Instagram quick replies format is not supported by current ManyChat API.
        # If needed in future, investigate ManyChat API documentation for Instagram-specific format.
        return []


# Singleton
_async_service: ManyChatAsyncService | None = None


def get_manychat_async_service(store: SessionStore) -> ManyChatAsyncService:
    """Get or create async service instance."""
    global _async_service
    if _async_service is None:
        _async_service = ManyChatAsyncService(store)
    return _async_service
