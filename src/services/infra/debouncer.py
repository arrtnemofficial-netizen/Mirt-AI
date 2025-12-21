import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class BufferedMessage:
    text: str = ""
    has_image: bool = False
    image_url: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)
    original_message: Any = None  # Aiogram Message object for replying


class MessageDebouncer:
    """
    Aggregates multiple messages from the same user into a single processing event.

    Supports two modes:
    1. Callback mode (Telegram): wait for delay, then call a function.
    2. Await mode (Webhooks): await result, returns None if superseded by newer message.
    """

    def __init__(self, delay: float = 2.0):
        self.delay = delay
        self.buffers: dict[str, list[BufferedMessage]] = {}
        self.timers: dict[str, asyncio.Task] = {}
        self.processing_callbacks: dict[str, Callable] = {}
        self.active_futures: dict[str, asyncio.Future] = {}

    # --- Callback Mode (Telegram) ---

    def register_callback(
        self, session_id: str, callback: Callable[[str, BufferedMessage], Coroutine]
    ):
        """Register the async function to call when debounce timer expires."""
        self.processing_callbacks[session_id] = callback

    async def add_message(
        self,
        session_id: str,
        message: BufferedMessage,
        callback: Callable[[str, BufferedMessage], Coroutine],
    ):
        """Add a message to the buffer and reset the timer (Callback Mode)."""

        # Register callback if not exists or update it
        self.processing_callbacks[session_id] = callback

        # Add to buffer
        self._append_to_buffer(session_id, message)

        # Reset timer
        self._reset_timer(session_id)

        logger.info(
            f"[DEBOUNCER] {session_id}: Message buffered (Callback Mode). Timer reset to {self.delay}s."
        )

    # --- Await Mode (ManyChat/Webhooks) ---

    async def wait_for_debounce(
        self, session_id: str, message: BufferedMessage
    ) -> BufferedMessage | None:
        """
        Add message and wait.
        Returns aggregated message if this request triggered the processing.
        Returns None if this request was superseded by a newer one.
        """
        # Add to buffer
        self._append_to_buffer(session_id, message)

        # Cancel previous future (tell it to return None)
        if session_id in self.active_futures:
            old_future = self.active_futures[session_id]
            if not old_future.done():
                old_future.set_result(None)

        # Create new future for this request
        future = asyncio.Future()
        self.active_futures[session_id] = future

        # Reset timer
        self._reset_timer(session_id, mode="await")

        logger.info(f"[DEBOUNCER] {session_id}: Message buffered (Await Mode). Waiting...")

        try:
            return await future
        except asyncio.CancelledError:
            return None

    # --- Internal Logic ---

    def _append_to_buffer(self, session_id: str, message: BufferedMessage):
        if session_id not in self.buffers:
            self.buffers[session_id] = []
        self.buffers[session_id].append(message)

    def _reset_timer(self, session_id: str, mode: str = "callback"):
        # Cancel existing timer
        if session_id in self.timers:
            self.timers[session_id].cancel()

        # Start new timer
        self.timers[session_id] = asyncio.create_task(self._timer_task(session_id, mode))

    async def _timer_task(self, session_id: str, mode: str):
        """Wait for delay, then trigger processing."""
        try:
            await asyncio.sleep(self.delay)

            if mode == "callback":
                await self._process_callback(session_id)
            else:
                self._process_future(session_id)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[DEBOUNCER] Error in timer task for {session_id}: {e}", exc_info=True)
            self._cleanup(session_id)

    async def _process_callback(self, session_id: str):
        """Aggregate messages and call the callback."""
        aggregated = self._aggregate_messages(session_id)
        if not aggregated:
            return

        callback = self.processing_callbacks.get(session_id)
        self._cleanup(session_id)

        if callback:
            try:
                await callback(session_id, aggregated)
            except Exception as e:
                logger.error(f"[DEBOUNCER] Error in callback for {session_id}: {e}", exc_info=True)

    def _process_future(self, session_id: str):
        """Aggregate messages and resolve the active future."""
        aggregated = self._aggregate_messages(session_id)
        future = self.active_futures.get(session_id)

        self._cleanup(session_id)

        if future and not future.done():
            future.set_result(aggregated)

    def _aggregate_messages(self, session_id: str) -> BufferedMessage | None:
        if session_id not in self.buffers or not self.buffers[session_id]:
            return None

        messages = self.buffers[session_id]

        full_text_parts = []
        has_image = False
        last_image_url = None
        merged_metadata = {}
        last_original_message = None

        for msg in messages:
            if msg.text:
                full_text_parts.append(msg.text)

            if msg.has_image:
                has_image = True
                last_image_url = msg.image_url

            if msg.extra_metadata:
                merged_metadata.update(msg.extra_metadata)

            last_original_message = msg.original_message

        combined_text = "\n".join(full_text_parts)

        logger.info(
            f"[DEBOUNCER] {session_id}: Aggregated {len(messages)} messages. "
            f"Final Text: '{combined_text[:50]}...'"
        )

        # Track metrics
        try:
            from src.services.core.observability import track_metric

            track_metric("debouncer_messages_aggregated", len(messages))
            if has_image:
                track_metric("debouncer_has_image", 1)
        except ImportError:
            pass  # Observability not available

        return BufferedMessage(
            text=combined_text,
            has_image=has_image,
            image_url=last_image_url,
            extra_metadata=merged_metadata,
            original_message=last_original_message,
        )

    def _cleanup(self, session_id: str):
        """Remove session data."""
        self.buffers.pop(session_id, None)
        self.timers.pop(session_id, None)
        self.active_futures.pop(session_id, None)
        # Note: we don't clear processing_callbacks to allow reuse

    def clear_session(self, session_id: str) -> None:
        """Clear any buffered/queued debounce state for a session."""
        if session_id in self.timers:
            self.timers[session_id].cancel()
        self._cleanup(session_id)
