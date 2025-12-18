"""Supabase implementation of SessionStore."""

from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy
from typing import Any, Callable

from src.agents import ConversationState
from src.conf.config import settings
from src.core.constants import AgentState as StateEnum
from src.services.session_store import InMemorySessionStore, SessionStore, _serialize_for_json
from src.services.supabase_client import get_supabase_client


logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker to prevent cascading failures when Supabase is down."""
    
    def __init__(self, failure_threshold: int = 5, timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
                logger.info("Circuit breaker entering HALF_OPEN state")
            else:
                raise Exception("Circuit breaker OPEN - Supabase operations disabled")
        
        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
                logger.info("Circuit breaker returning to CLOSED state")
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                logger.error(
                    "Circuit breaker OPENED after %d failures. Supabase disabled for %.1fs",
                    self.failure_count,
                    self.timeout
                )
            
            raise e


# Global circuit breaker instance
_circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=60.0)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 5.0,
    backoff_factor: float = 2.0,
) -> Callable:
    """Decorator for retrying database operations with exponential backoff."""
    def decorator(func: Callable) -> Callable:
        def _in_async_loop() -> bool:
            try:
                asyncio.get_running_loop()
                return True
            except RuntimeError:
                return False

        async def async_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    if asyncio.iscoroutinefunction(func):
                        return await func(*args, **kwargs)
                    else:
                        return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # Don't retry on certain errors
                    if "authentication" in str(e).lower() or "unauthorized" in str(e).lower():
                        break
                        
                    if attempt < max_retries:
                        delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                        logger.warning(
                            "Supabase operation failed (attempt %d/%d), retrying in %.1fs: %s",
                            attempt + 1,
                            max_retries + 1,
                            delay,
                            e
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "Supabase operation failed after %d attempts: %s",
                            max_retries + 1,
                            e
                        )
            
            raise last_exception
        
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # Don't retry on certain errors
                    if "authentication" in str(e).lower() or "unauthorized" in str(e).lower():
                        break
                        
                    if attempt < max_retries:
                        delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                        logger.warning(
                            "Supabase operation failed (attempt %d/%d), retrying in %.1fs: %s",
                            attempt + 1,
                            max_retries + 1,
                            delay,
                            e
                        )
                        # IMPORTANT: get()/save() are called from async request handlers.
                        # Never block the asyncio event loop.
                        if not _in_async_loop():
                            time.sleep(delay)
                    else:
                        logger.error(
                            "Supabase operation failed after %d attempts: %s",
                            max_retries + 1,
                            e
                        )
            
            raise last_exception
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


class SupabaseSessionStore:
    """Session storage using Supabase table 'mirt_sessions'."""

    def __init__(self, table_name: str | None = None) -> None:
        if table_name is None:
            table_name = settings.SUPABASE_TABLE or "mirt_sessions"
        self.table_name = table_name
        # In-process fallback store to keep sessions alive when Supabase is down
        # or returns transient errors (e.g. 521 Web server is down).
        # This ensures UX is not broken even if remote persistence is unavailable.
        self._fallback_store: InMemorySessionStore = InMemorySessionStore()
        logger.info("SupabaseSessionStore initialized with table '%s'", self.table_name)

    def _fetch_from_supabase(self, session_id: str) -> ConversationState | None:
        """Fetch session from Supabase with circuit breaker protection."""
        client = get_supabase_client()
        if not client:
            return None

        def _do_fetch():
            response = (
                client.table(self.table_name)
                .select("state")
                .eq("session_id", session_id)
                .limit(1)
                .execute()
            )

            if response.data and len(response.data) > 0:
                state_data = response.data[0].get("state")
                if state_data:
                    return deepcopy(state_data)
            return None

        try:
            return _circuit_breaker.call(_do_fetch)
        except Exception as e:
            if "Circuit breaker" in str(e):
                logger.warning("Circuit breaker blocked Supabase fetch for session %s", session_id)
            else:
                logger.error("Failed to fetch session %s from Supabase: %s", session_id, e)
            return None

    @retry_with_backoff(max_retries=2, base_delay=0.3, max_delay=2.0)  # Reduced retries since circuit breaker handles failures
    def get(self, session_id: str) -> ConversationState:
        """Return stored state or a fresh empty state."""
        supabase_state = self._fetch_from_supabase(session_id)

        # Always fetch fallback state (may be empty/new for first-time sessions)
        fallback_state = self._fallback_store.get(session_id)

        # If Supabase returned nothing or failed, rely entirely on fallback
        if supabase_state is None:
            # Ensure minimal metadata is present
            metadata = fallback_state.get("metadata", {})
            metadata.setdefault("session_id", session_id)
            fallback_state["metadata"] = metadata
            return fallback_state

        # Both Supabase and fallback have some state: choose the fresher one
        sup_step = supabase_state.get("step_number", 0)
        fb_step = fallback_state.get("step_number", 0)
        chosen = supabase_state if sup_step >= fb_step else fallback_state

        # Ensure required metadata fields
        metadata = chosen.get("metadata", {})
        metadata.setdefault("session_id", session_id)
        chosen["metadata"] = metadata

        # Keep fallback in sync with the chosen latest state
        self._fallback_store.save(session_id, chosen)

        return deepcopy(chosen)

    def _save_to_supabase(self, session_id: str, state: ConversationState) -> bool:
        """Save session to Supabase with circuit breaker protection."""
        client = get_supabase_client()
        if not client:
            return False

        def _do_save():
            # Serialize state to handle LangChain objects
            serialized_state = _serialize_for_json(dict(state))

            # Upsert session
            data = {
                "session_id": session_id,
                "state": serialized_state,
                # 'updated_at' is usually handled by DB default/trigger, but we can explicit if needed
            }

            client.table(self.table_name).upsert(data, on_conflict="session_id").execute()
            return True

        try:
            return _circuit_breaker.call(_do_save)
        except Exception as e:
            if "Circuit breaker" in str(e):
                logger.warning("Circuit breaker blocked Supabase save for session %s", session_id)
            else:
                logger.error("Failed to save session %s to Supabase: %s", session_id, e)
            return False

    @retry_with_backoff(max_retries=2, base_delay=0.3, max_delay=2.0)  # Reduced retries since circuit breaker handles failures
    def save(self, session_id: str, state: ConversationState) -> None:
        """Persist the current state for the session."""
        # Always keep in-memory fallback up to date so UX is stable even if
        # Supabase is temporarily unavailable.
        try:
            self._fallback_store.save(session_id, state)
        except Exception as e:  # Extremely unlikely, but don't block main flow
            logger.warning(
                "Failed to save session %s to in-memory fallback store: %s",
                session_id,
                e,
            )

        # Try to save to Supabase with circuit breaker protection
        self._save_to_supabase(session_id, state)

    def delete(self, session_id: str) -> bool:
        """Delete session state. Returns True if session existed."""
        # Delete from fallback store first
        existed_in_fallback = self._fallback_store.delete(session_id)

        client = get_supabase_client()
        if not client:
            logger.warning(
                "Supabase client not available, only deleted from fallback for session %s",
                session_id,
            )
            return existed_in_fallback

        try:
            response = (
                client.table(self.table_name)
                .delete()
                .eq("session_id", session_id)
                .execute()
            )
            # Check if any rows were deleted
            existed_in_supabase = bool(response.data and len(response.data) > 0)
            logger.info(
                "Deleted session %s from Supabase (existed=%s)",
                session_id,
                existed_in_supabase,
            )
            return existed_in_fallback or existed_in_supabase
        except Exception as e:
            logger.error("Failed to delete session %s from Supabase: %s", session_id, e)
            return existed_in_fallback

    def _create_empty_state(self, session_id: str) -> ConversationState:
        """Create a fresh empty state."""
        return ConversationState(
            messages=[],
            metadata={"session_id": session_id},
            current_state=StateEnum.default(),
        )


def create_supabase_store() -> SessionStore | None:
    """Factory to create Supabase store if configured."""
    client = get_supabase_client()
    if not client:
        return None
    return SupabaseSessionStore()
