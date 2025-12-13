"""Supabase implementation of SessionStore."""

from __future__ import annotations

import logging
from copy import deepcopy

from src.agents import ConversationState
from src.conf.config import settings
from src.core.constants import AgentState as StateEnum
from src.services.session_store import InMemorySessionStore, SessionStore, _serialize_for_json
from src.services.supabase_client import get_supabase_client


logger = logging.getLogger(__name__)


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

    def get(self, session_id: str) -> ConversationState:
        """Return stored state or a fresh empty state."""
        client = get_supabase_client()

        supabase_state: ConversationState | None = None

        if client:
            try:
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
                        supabase_state = deepcopy(state_data)
            except Exception as e:
                logger.error("Failed to fetch session %s from Supabase: %s", session_id, e)
        else:
            logger.warning(
                "Supabase client not available, using in-memory session store for %s",
                session_id,
            )

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

        client = get_supabase_client()
        if not client:
            logger.warning(
                "Supabase client not available, skipping remote save for session %s",
                session_id,
            )
            return

        try:
            # Serialize state to handle LangChain objects
            serialized_state = _serialize_for_json(dict(state))

            # Upsert session
            data = {
                "session_id": session_id,
                "state": serialized_state,
                # 'updated_at' is usually handled by DB default/trigger, but we can explicit if needed
            }

            client.table(self.table_name).upsert(data, on_conflict="session_id").execute()

        except Exception as e:
            logger.error("Failed to save session %s to Supabase: %s", session_id, e)

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
