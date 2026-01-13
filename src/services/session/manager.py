"""
Session Management Service.
===========================
Handles loading, initializing, and saving conversation state.
Ensures state consistency and thread safety for database operations.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
import uuid
from typing import TYPE_CHECKING, Any

from src.core.models import BaseConversationState as ConversationState

if TYPE_CHECKING:
    from src.services.storage import SessionStore

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages conversation sessions, including:
    - Loading from persistent storage (with timeouts)
    - Initializing default state for new sessions
    - Saving updates back to storage
    - Managing session metadata (IDs, flags)
    """

    def __init__(self, store: SessionStore):
        self.store = store

    async def load_session(
        self, session_id: str, extra_metadata: dict[str, Any] | None = None
    ) -> ConversationState:
        """
        Load session specific state or create a fresh one if missing.
        Handles timeouts and initialization logic.
        """
        state: ConversationState | None = None
        _get_start = _time.time()

        # 1. Try to load from DB
        try:
            # Database operations are wrapped in to_thread() to avoid blocking the async loop
            state = await asyncio.wait_for(
                asyncio.to_thread(self.store.get, session_id),
                timeout=2.5,
            )
            logger.info(
                "[SESSION %s] ⏱️ session_store.get took %.2fs",
                session_id,
                _time.time() - _get_start,
            )
        except TimeoutError:
            logger.warning(
                "[SESSION %s] session_store.get timed out (>2.5s); continuing with empty state",
                session_id,
            )
            state = None
        except Exception as e:
            logger.error(
                "[SESSION %s] Failed to load session: %s. Using empty state.",
                session_id,
                e
            )
            state = None

        # 2. Check structure / Initialize if missing
        if not state or not isinstance(state, dict):
            state = ConversationState(
                messages=[],
                metadata={
                    "session_id": session_id,
                    "vision_greeted": False,
                    "has_image": False,
                },
                current_state="STATE_0_INIT",
                dialog_phase="INIT",
                should_escalate=False,
                has_image=False,
                detected_intent=None,
                selected_products=[],
                offered_products=[],
                step_number=0,
            )

        # 3. Ensure required keys exist (for legacy/migration compatibility)
        if "messages" not in state:
            state["messages"] = []
        if "metadata" not in state:
            state["metadata"] = {"session_id": session_id, "vision_greeted": False}

        # Ensure core identifiers are present
        state["metadata"].setdefault("session_id", session_id)
        # Fallback thread_id to session_id if missing
        state["metadata"].setdefault(
            "thread_id", state["metadata"].get("thread_id", session_id)
        )
        # Ensure top-level session_id is always present
        state.setdefault("session_id", session_id)

        # 4. Reset transient flags (like image flags) that shouldn't persist across turns
        # This prevents stale image_url from previous messages affecting routing
        state["has_image"] = False
        state["image_url"] = None
        state["metadata"]["has_image"] = False
        state["metadata"]["image_url"] = None

        # 5. Apply extra metadata from current request (e.g. webhook payload)
        if extra_metadata:
            state["metadata"].update(extra_metadata)

            # Mirror critical flags (has_image) to top-level
            if extra_metadata.get("has_image"):
                image_url = extra_metadata.get("image_url")
                if isinstance(image_url, str):
                    trimmed = image_url.strip()
                    if trimmed.startswith(("http://", "https://")) and len(trimmed) <= 2000:
                        state["has_image"] = True
                        state["image_url"] = trimmed
                        state["metadata"]["image_url"] = trimmed

        # 6. Generate Trace ID for Observability
        trace_id = None
        if extra_metadata and isinstance(extra_metadata, dict):
            trace_id = str(extra_metadata.get("trace_id") or "").strip() or None
        if not trace_id:
            trace_id = str(uuid.uuid4())
        state["trace_id"] = trace_id

        return state

    async def save_session(self, session_id: str, state: ConversationState) -> None:
        """
        Persist the session state to storage.
        """
        try:
            # CRITICAL: Use to_thread() to avoid blocking event loop!
            await asyncio.to_thread(self.store.save, session_id, state)
        except Exception as e:
            logger.error(
                "[SESSION %s] Failed to save session state: %s",
                session_id,
                e
            )
            # We log but do not raise, to avoid crashing the response flow
            # (though data loss is critical, crashing might be worse here)
