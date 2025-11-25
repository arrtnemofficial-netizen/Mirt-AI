"""Message store implementations with Supabase persistence."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Protocol

from supabase import Client

from src.services.supabase_client import get_supabase_client
from src.conf.config import settings


@dataclass
class StoredMessage:
    session_id: str
    role: str
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = field(default_factory=list)


class MessageStore(Protocol):
    def append(self, message: StoredMessage) -> None:
        ...

    def list(self, session_id: str) -> List[StoredMessage]:
        ...

    def delete(self, session_id: str) -> None:
        ...


class InMemoryMessageStore:
    def __init__(self) -> None:
        self._messages: dict[str, list[StoredMessage]] = {}

    def append(self, message: StoredMessage) -> None:
        self._messages.setdefault(message.session_id, []).append(message)

    def list(self, session_id: str) -> List[StoredMessage]:
        return list(self._messages.get(session_id, []))

    def delete(self, session_id: str) -> None:
        self._messages.pop(session_id, None)


class SupabaseMessageStore:
    def __init__(self, client: Client, table: str = "messages") -> None:
        self.client = client
        self.table = table

    def append(self, message: StoredMessage) -> None:
        payload = {
            "session_id": message.session_id,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
            "tags": message.tags,
        }
        self.client.table(self.table).insert(payload).execute()

    def list(self, session_id: str) -> List[StoredMessage]:
        response = (
            self.client.table(self.table)
            .select("session_id, role, content, created_at, tags")
            .eq("session_id", session_id)
            .order("created_at")
            .execute()
        )
        data = getattr(response, "data", None)  # type: ignore[attr-defined]
        if not data:
            return []
        messages: list[StoredMessage] = []
        for row in data:
            created_at = row.get("created_at")
            try:
                dt = datetime.fromisoformat(created_at)
            except Exception:
                dt = datetime.now(timezone.utc)
            messages.append(
                StoredMessage(
                    session_id=row.get("session_id", ""),
                    role=row.get("role", "assistant"),
                    content=row.get("content", ""),
                    created_at=dt,
                    tags=row.get("tags") or [],
                )
            )
        return messages

    def delete(self, session_id: str) -> None:
        self.client.table(self.table).delete().eq("session_id", session_id).execute()


def create_message_store() -> MessageStore:
    client = get_supabase_client()
    if client:
        return SupabaseMessageStore(client, table=settings.SUPABASE_MESSAGES_TABLE)
    return InMemoryMessageStore()

