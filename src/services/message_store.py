import builtins
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from supabase import Client

from src.core.constants import DBTable
from src.services.supabase_client import get_supabase_client


logger = logging.getLogger(__name__)


@dataclass
class StoredMessage:
    session_id: str
    role: str
    content: str
    user_id: int | None = None
    content_type: str = "text"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = field(default_factory=list)


class MessageStore(Protocol):
    def append(self, message: StoredMessage) -> None: ...

    def list(self, session_id: str) -> list[StoredMessage]: ...

    def delete(self, session_id: str) -> None: ...


class InMemoryMessageStore:
    def __init__(self) -> None:
        self._messages: dict[str, list[StoredMessage]] = {}

    def append(self, message: StoredMessage) -> None:
        self._messages.setdefault(message.session_id, []).append(message)

    def list(self, session_id: str) -> list[StoredMessage]:
        return list(self._messages.get(session_id, []))

    def delete(self, session_id: str) -> None:
        self._messages.pop(session_id, None)


class SupabaseMessageStore:
    """Message store using messages table schema."""

    def __init__(self, client: Client, table: str = DBTable.MESSAGES) -> None:
        self.client = client
        self.table = table

    def append(self, message: StoredMessage) -> None:
        """Insert message and update interaction timestamp."""
        payload = {
            "session_id": message.session_id,
            "role": message.role,
            "content": message.content,
            "content_type": message.content_type,
            "created_at": message.created_at.isoformat(),
        }

        if message.user_id:
            payload["user_id"] = message.user_id
            self._update_user_interaction(message.user_id)

        try:
            self.client.table(self.table).insert(payload).execute()
        except Exception as e:
            logger.error("Failed to append message to Supabase: %s", e)
            raise

    def _update_user_interaction(self, user_id: int) -> None:
        """Update last_interaction_at for user."""
        try:
            self.client.table(DBTable.USERS).upsert(
                {
                    "user_id": user_id,
                    "last_interaction_at": datetime.now(UTC).isoformat(),
                }
            ).execute()
        except Exception as e:
            # Log warning but don't fail the main message insert flow
            logger.warning("Failed to update last_interaction_at for user %s: %s", user_id, e)

    def list(self, session_id: str) -> list[StoredMessage]:
        """Get all messages for a session."""
        try:
            response = (
                self.client.table(self.table)
                .select("user_id, session_id, role, content, content_type, created_at")
                .eq("session_id", session_id)
                .order("created_at")
                .execute()
            )
        except Exception as e:
            logger.error("Failed to list messages for session %s: %s", session_id, e)
            return []

        return self._parse_response(response)

    def list_by_user(self, user_id: int) -> builtins.list[StoredMessage]:
        """Get all messages for a user."""
        try:
            response = (
                self.client.table(self.table)
                .select("user_id, session_id, role, content, content_type, created_at")
                .eq("user_id", user_id)
                .order("created_at")
                .execute()
            )
        except Exception as e:
            logger.error("Failed to list messages for user %s: %s", user_id, e)
            return []

        return self._parse_response(response)

    def _parse_response(self, response: Any) -> builtins.list[StoredMessage]:
        """Helper to parse Supabase response."""
        data = getattr(response, "data", None)
        if not data:
            return []

        messages: list[StoredMessage] = []
        for row in data:
            created_at = row.get("created_at")
            try:
                dt = datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                dt = datetime.now(UTC)

            messages.append(
                StoredMessage(
                    session_id=row.get("session_id", ""),
                    role=row.get("role", "assistant"),
                    content=row.get("content", ""),
                    user_id=row.get("user_id"),
                    content_type=row.get("content_type", "text"),
                    created_at=dt,
                    tags=[],
                )
            )
        return messages

    def delete(self, session_id: str) -> None:
        self.client.table(self.table).delete().eq("session_id", session_id).execute()

    def delete_by_user(self, user_id: int) -> None:
        self.client.table(self.table).delete().eq("user_id", user_id).execute()


def create_message_store() -> MessageStore:
    client = get_supabase_client()
    if client:
        return SupabaseMessageStore(client)
    return InMemoryMessageStore()
