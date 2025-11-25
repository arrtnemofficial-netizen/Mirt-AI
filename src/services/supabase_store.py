"""Supabase-backed session store for persisting chat state."""
from __future__ import annotations

from typing import Any, Dict, Optional

from supabase import Client, create_client

from src.agents.graph import AgentState
from src.conf.config import settings
from src.services.session_store import SessionStore


class SupabaseSessionStore(SessionStore):
    """Persist AgentState rows inside a Supabase table.

    Expects a table with at least columns:
    - session_id (text, primary key)
    - state (jsonb)
    """

    def __init__(self, client: Client, table: str = "agent_sessions") -> None:
        self.client = client
        self.table = table

    def get(self, session_id: str) -> AgentState:
        response = (
            self.client.table(self.table)
            .select("state")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
        )
        data: Optional[list[Dict[str, Any]]] = getattr(response, "data", None)  # type: ignore[attr-defined]
        if data and data[0].get("state"):
            state_data = data[0]["state"]
            # Defensive defaulting in case metadata is missing
            state_data.setdefault("metadata", {})
            state_data.setdefault("messages", [])
            state_data.setdefault("current_state", "STATE0_INIT")
            return AgentState(**state_data)
        return AgentState(messages=[], metadata={}, current_state="STATE0_INIT")

    def save(self, session_id: str, state: AgentState) -> None:
        payload = {"session_id": session_id, "state": state}
        (
            self.client.table(self.table)
            .upsert(payload)
            .execute()
        )


def build_supabase_client() -> Optional[Client]:
    """Return a Supabase client if URL/key are configured."""

    if not settings.SUPABASE_URL or not settings.SUPABASE_API_KEY.get_secret_value():
        return None
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_API_KEY.get_secret_value(),
    )


def create_supabase_store() -> Optional[SupabaseSessionStore]:
    """Factory that builds a SupabaseSessionStore or None when disabled."""

    client = build_supabase_client()
    if not client:
        return None
    return SupabaseSessionStore(client, table=settings.SUPABASE_TABLE)
