"""Supabase implementation of SessionStore."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from src.agents import ConversationState
from src.core.constants import AgentState as StateEnum
from src.services.session_store import SessionStore, _serialize_for_json
from src.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class SupabaseSessionStore:
    """Session storage using Supabase table 'mirt_sessions'."""

    def __init__(self, table_name: str = "mirt_sessions") -> None:
        self.table_name = table_name

    def get(self, session_id: str) -> ConversationState:
        """Return stored state or a fresh empty state."""
        client = get_supabase_client()
        if not client:
            logger.warning("Supabase client not available, returning empty state")
            return self._create_empty_state(session_id)

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
                    return deepcopy(state_data)
        except Exception as e:
            logger.error(f"Failed to fetch session {session_id}: {e}")

        return self._create_empty_state(session_id)

    def save(self, session_id: str, state: ConversationState) -> None:
        """Persist the current state for the session."""
        client = get_supabase_client()
        if not client:
            logger.warning("Supabase client not available, skipping save")
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

            client.table(self.table_name).upsert(
                data, on_conflict="session_id"
            ).execute()

        except Exception as e:
            logger.error(f"Failed to save session {session_id}: {e}")

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
