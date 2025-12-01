"""Supabase-backed session store for persisting chat state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage

from src.agents import ConversationState
from src.conf.config import settings
from src.core.constants import AgentState as StateEnum
from src.services.session_store import SessionStore
from src.services.supabase_client import get_supabase_client


if TYPE_CHECKING:
    from supabase import Client


def _serialize_for_json(value: Any) -> Any:
    """Recursively serialize values, converting LangChain Message objects to dicts."""
    if isinstance(value, BaseMessage):
        return {
            "type": value.type,
            "content": value.content,
            "additional_kwargs": getattr(value, "additional_kwargs", {}),
        }
    elif isinstance(value, dict):
        return {k: _serialize_for_json(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_serialize_for_json(item) for item in value]
    else:
        return value


class SupabaseSessionStore(SessionStore):
    """Persist AgentState rows inside a Supabase table.

    Expects a table with at least columns:
    - session_id (text, primary key)
    - state (jsonb)
    """

    def __init__(self, client: Client, table: str = "agent_sessions") -> None:
        self.client = client
        self.table = table

    def get(self, session_id: str) -> ConversationState:
        response = (
            self.client.table(self.table)
            .select("state")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
        )
        data: list[dict[str, Any]] | None = getattr(response, "data", None)  # type: ignore[attr-defined]
        if data and data[0].get("state"):
            state_data = data[0]["state"]
            # Defensive defaulting in case metadata is missing
            state_data.setdefault("metadata", {})
            state_data.setdefault("messages", [])
            state_data.setdefault("current_state", StateEnum.default())
            return ConversationState(**state_data)
        return ConversationState(messages=[], metadata={}, current_state=StateEnum.default())

    def save(self, session_id: str, state: ConversationState) -> None:
        # Serialize state to handle LangChain Message objects
        serialized_state = _serialize_for_json(dict(state))
        payload = {"session_id": session_id, "state": serialized_state}
        (self.client.table(self.table).upsert(payload).execute())


def create_supabase_store() -> SupabaseSessionStore | None:
    """Factory that builds a SupabaseSessionStore or None when disabled."""

    client = get_supabase_client()
    if not client:
        return None
    return SupabaseSessionStore(client, table=settings.SUPABASE_TABLE)
