import asyncio
import json
import logging
import time
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


class RedisDebouncer:
    """
    Redis-backed debouncer for multi-instance deployments.
    
    Uses Redis to store buffers and timer state, allowing debouncing
    to work across multiple server instances.
    
    Falls back to in-memory behavior if Redis is unavailable (but logs warning).
    """

    def __init__(self, delay: float = 2.0):
        self.delay = delay
        self._redis_client = None
        self._redis_available = False
        self._fallback_debouncer: MessageDebouncer | None = None
        self._initialize_redis()

    def _initialize_redis(self):
        """Initialize Redis client if available."""
        try:
            import os

            import redis

            from src.conf.config import settings

            redis_url = os.getenv("REDIS_URL") or settings.REDIS_URL
            if not redis_url:
                logger.debug("[REDIS_DEBOUNCER] Redis URL not configured, using fallback")
                self._fallback_debouncer = MessageDebouncer(delay=self.delay)
                return

            self._redis_client = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            self._redis_client.ping()
            self._redis_available = True
            logger.info("[REDIS_DEBOUNCER] Redis connected, using distributed debouncing")
        except Exception as e:
            logger.warning(
                "[REDIS_DEBOUNCER] Redis not available, falling back to in-memory: %s", e
            )
            self._redis_available = False
            self._fallback_debouncer = MessageDebouncer(delay=self.delay)

    def _get_redis_key(self, session_id: str, key_type: str) -> str:
        """Generate Redis key for session data."""
        return f"debouncer:{key_type}:{session_id}"

    def _serialize_message(self, message: BufferedMessage) -> str:
        """Serialize BufferedMessage to JSON string."""
        return json.dumps({
            "text": message.text,
            "has_image": message.has_image,
            "image_url": message.image_url,
            "extra_metadata": message.extra_metadata,
        }, default=str)

    def _deserialize_message(self, data: str) -> BufferedMessage:
        """Deserialize JSON string to BufferedMessage."""
        obj = json.loads(data)
        return BufferedMessage(
            text=obj.get("text", ""),
            has_image=obj.get("has_image", False),
            image_url=obj.get("image_url"),
            extra_metadata=obj.get("extra_metadata", {}),
        )

    def _use_fallback(self):
        """Check if we should use fallback debouncer."""
        if not self._redis_available or self._fallback_debouncer is not None:
            return True
        return False

    # --- Callback Mode (Telegram) ---

    def register_callback(
        self, session_id: str, callback: Callable[[str, BufferedMessage], Coroutine]
    ):
        """Register the async function to call when debounce timer expires."""
        if self._use_fallback():
            return self._fallback_debouncer.register_callback(session_id, callback)
        
        # Store callback in Redis (with short TTL)
        try:
            callback_key = self._get_redis_key(session_id, "callback")
            # Note: We can't serialize callbacks, so we store a marker
            # The actual callback needs to be registered per-instance
            # For now, we'll use a hybrid approach: callback stored in-memory per instance
            # but buffers/timers in Redis
            if not hasattr(self, "_callbacks"):
                self._callbacks: dict[str, Callable] = {}
            self._callbacks[session_id] = callback
        except Exception as e:
            logger.error(f"[REDIS_DEBOUNCER] Failed to register callback: {e}")
            if self._fallback_debouncer:
                self._fallback_debouncer.register_callback(session_id, callback)

    async def add_message(
        self,
        session_id: str,
        message: BufferedMessage,
        callback: Callable[[str, BufferedMessage], Coroutine],
    ):
        """Add a message to the buffer and reset the timer (Callback Mode)."""
        if self._use_fallback():
            return await self._fallback_debouncer.add_message(session_id, message, callback)

        try:
            # Register callback (in-memory per instance)
            if not hasattr(self, "_callbacks"):
                self._callbacks: dict[str, Callable] = {}
            self._callbacks[session_id] = callback

            # Add to buffer in Redis
            buffer_key = self._get_redis_key(session_id, "buffer")
            message_data = self._serialize_message(message)
            self._redis_client.lpush(buffer_key, message_data)
            self._redis_client.expire(buffer_key, int(self.delay * 2))  # Auto-expire

            # Reset timer in Redis
            timer_key = self._get_redis_key(session_id, "timer")
            expiry_time = time.time() + self.delay
            self._redis_client.setex(timer_key, int(self.delay * 2), str(expiry_time))

            # Start timer task (per-instance, but checks Redis for actual expiry)
            await self._reset_timer_redis(session_id, mode="callback")

            logger.info(
                f"[REDIS_DEBOUNCER] {session_id}: Message buffered (Callback Mode). Timer reset to {self.delay}s."
            )
        except Exception as e:
            logger.error(f"[REDIS_DEBOUNCER] Failed to add message, using fallback: {e}")
            if self._fallback_debouncer:
                await self._fallback_debouncer.add_message(session_id, message, callback)

    # --- Await Mode (ManyChat/Webhooks) ---

    async def wait_for_debounce(
        self, session_id: str, message: BufferedMessage
    ) -> BufferedMessage | None:
        """
        Add message and wait.
        Returns aggregated message if this request triggered the processing.
        Returns None if this request was superseded by a newer one.
        """
        if self._use_fallback():
            return await self._fallback_debouncer.wait_for_debounce(session_id, message)

        try:
            # Add to buffer in Redis
            buffer_key = self._get_redis_key(session_id, "buffer")
            message_data = self._serialize_message(message)
            self._redis_client.lpush(buffer_key, message_data)
            self._redis_client.expire(buffer_key, int(self.delay * 2))

            # Cancel previous future (in-memory per instance)
            if not hasattr(self, "_active_futures"):
                self._active_futures: dict[str, asyncio.Future] = {}
            
            if session_id in self._active_futures:
                old_future = self._active_futures[session_id]
                if not old_future.done():
                    old_future.set_result(None)

            # Create new future for this request
            future = asyncio.Future()
            self._active_futures[session_id] = future

            # Reset timer
            await self._reset_timer_redis(session_id, mode="await")

            logger.info(f"[REDIS_DEBOUNCER] {session_id}: Message buffered (Await Mode). Waiting...")

            try:
                return await future
            except asyncio.CancelledError:
                return None
        except Exception as e:
            logger.error(f"[REDIS_DEBOUNCER] Failed to wait for debounce, using fallback: {e}")
            if self._fallback_debouncer:
                return await self._fallback_debouncer.wait_for_debounce(session_id, message)
            return None

    # --- Internal Logic ---

    async def _reset_timer_redis(self, session_id: str, mode: str = "callback"):
        """Reset timer using Redis-backed check."""
        timer_key = self._get_redis_key(session_id, "timer")
        expiry_time = time.time() + self.delay
        
        try:
            # Set expiry time in Redis
            self._redis_client.setex(timer_key, int(self.delay * 2), str(expiry_time))
            
            # Start local timer task that checks Redis
            if not hasattr(self, "_timers"):
                self._timers: dict[str, asyncio.Task] = {}
            
            if session_id in self._timers:
                self._timers[session_id].cancel()
            
            self._timers[session_id] = asyncio.create_task(
                self._timer_task_redis(session_id, expiry_time, mode)
            )
        except Exception as e:
            logger.error(f"[REDIS_DEBOUNCER] Failed to reset timer: {e}")
            if self._fallback_debouncer:
                await self._fallback_debouncer._reset_timer(session_id, mode)

    async def _timer_task_redis(self, session_id: str, expected_expiry: float, mode: str):
        """Wait for delay, checking Redis for actual expiry time."""
        try:
            # Wait for delay
            await asyncio.sleep(self.delay)
            
            # Check if timer was reset (newer expiry time in Redis)
            timer_key = self._get_redis_key(session_id, "timer")
            current_expiry_str = self._redis_client.get(timer_key)
            
            if current_expiry_str:
                current_expiry = float(current_expiry_str)
                # If expiry was updated (newer), this timer is obsolete
                if current_expiry > expected_expiry + 0.1:  # Small tolerance
                    logger.debug(f"[REDIS_DEBOUNCER] {session_id}: Timer reset detected, cancelling")
                    return
            
            # Timer expired, process
            if mode == "callback":
                await self._process_callback_redis(session_id)
            else:
                await self._process_future_async(session_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[REDIS_DEBOUNCER] Error in timer task for {session_id}: {e}", exc_info=True)
            self._cleanup_redis(session_id)

    async def _process_callback_redis(self, session_id: str):
        """Aggregate messages from Redis and call the callback."""
        aggregated = await self._aggregate_messages_redis(session_id)
        if not aggregated:
            return

        callback = None
        if hasattr(self, "_callbacks"):
            callback = self._callbacks.get(session_id)
        
        self._cleanup_redis(session_id)

        if callback:
            try:
                await callback(session_id, aggregated)
            except Exception as e:
                logger.error(f"[REDIS_DEBOUNCER] Error in callback for {session_id}: {e}", exc_info=True)

    def _process_future_redis(self, session_id: str):
        """Aggregate messages from Redis and resolve the active future."""
        # Schedule async aggregation
        asyncio.create_task(self._process_future_async(session_id))

    async def _process_future_async(self, session_id: str):
        """Async helper to aggregate and resolve future."""
        aggregated = await self._aggregate_messages_redis(session_id)
        
        if not hasattr(self, "_active_futures"):
            return
        
        future = self._active_futures.get(session_id)
        self._cleanup_redis(session_id)

        if future and not future.done():
            future.set_result(aggregated)

    async def _aggregate_messages_redis(self, session_id: str) -> BufferedMessage | None:
        """Aggregate messages from Redis buffer."""
        try:
            buffer_key = self._get_redis_key(session_id, "buffer")
            messages_data = self._redis_client.lrange(buffer_key, 0, -1)
            
            if not messages_data:
                return None

            messages = [self._deserialize_message(data) for data in messages_data]

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
                f"[REDIS_DEBOUNCER] {session_id}: Aggregated {len(messages)} messages. "
                f"Final Text: '{combined_text[:50]}...'"
            )

            # Track metrics
            try:
                from src.services.core.observability import track_metric

                track_metric("debouncer_messages_aggregated", len(messages))
                if has_image:
                    track_metric("debouncer_has_image", 1)
            except ImportError:
                pass

            return BufferedMessage(
                text=combined_text,
                has_image=has_image,
                image_url=last_image_url,
                extra_metadata=merged_metadata,
                original_message=last_original_message,
            )
        except Exception as e:
            logger.error(f"[REDIS_DEBOUNCER] Failed to aggregate messages: {e}")
            return None

    def _cleanup_redis(self, session_id: str):
        """Remove session data from Redis and local state."""
        try:
            buffer_key = self._get_redis_key(session_id, "buffer")
            timer_key = self._get_redis_key(session_id, "timer")
            self._redis_client.delete(buffer_key, timer_key)
        except Exception:
            pass
        
        # Cleanup local state
        if hasattr(self, "_timers") and session_id in self._timers:
            self._timers[session_id].cancel()
            del self._timers[session_id]
        
        if hasattr(self, "_active_futures") and session_id in self._active_futures:
            del self._active_futures[session_id]
        
        # Note: we don't clear callbacks to allow reuse

    def clear_session(self, session_id: str) -> None:
        """Clear any buffered/queued debounce state for a session."""
        if self._use_fallback():
            return self._fallback_debouncer.clear_session(session_id)
        
        if hasattr(self, "_timers") and session_id in self._timers:
            self._timers[session_id].cancel()
        self._cleanup_redis(session_id)


def create_debouncer(delay: float = 2.0) -> MessageDebouncer | RedisDebouncer:
    """
    Factory function to create appropriate debouncer.
    
    Returns RedisDebouncer if Redis is available, otherwise MessageDebouncer.
    Automatically falls back to in-memory debouncer if Redis becomes unavailable.
    
    Args:
        delay: Debounce delay in seconds
    
    Returns:
        MessageDebouncer or RedisDebouncer instance
    """
    try:
        debouncer = RedisDebouncer(delay=delay)
        # Check if Redis is actually available
        if debouncer._redis_available:
            logger.info("[DEBOUNCER] Using Redis-backed debouncer for multi-instance support")
            return debouncer
        else:
            logger.info("[DEBOUNCER] Redis unavailable, using in-memory debouncer")
            return debouncer._fallback_debouncer or MessageDebouncer(delay=delay)
    except Exception as e:
        logger.warning(f"[DEBOUNCER] Failed to create Redis debouncer, using in-memory: {e}")
        return MessageDebouncer(delay=delay)
