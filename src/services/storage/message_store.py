import builtins
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from src.core.constants import DBTable


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


def create_message_store() -> MessageStore:
    """Factory to create message store (PostgreSQL preferred, fallback to in-memory)."""
    # Try PostgreSQL first
    try:
        from .postgres_message_store import create_postgres_message_store
        postgres_store = create_postgres_message_store()
        if postgres_store:
            return postgres_store
    except Exception as e:
        logger.warning("PostgreSQL message store not available: %s", e)
    
    # Fallback to in-memory
    return InMemoryMessageStore()
