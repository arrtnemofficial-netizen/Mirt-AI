"""PostgreSQL implementation of MessageStore."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore

from .message_store import MessageStore, StoredMessage
from src.conf.config import settings
from src.core.constants import DBTable
from .postgres_pool import get_postgres_url

logger = logging.getLogger(__name__)


class PostgresMessageStore:
    """Message store using PostgreSQL messages table."""

    def __init__(self, table: str = DBTable.MESSAGES) -> None:
        self.table = table
        logger.info("PostgresMessageStore initialized with table '%s'", self.table)

    def append(self, message: StoredMessage) -> None:
        """Insert message and update interaction timestamp (sync)."""
        if psycopg is None:
            logger.error("psycopg not installed")
            raise RuntimeError("psycopg not installed")
        
        try:
            url = get_postgres_url()
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    # Insert message
                    cur.execute(
                        f"""
                        INSERT INTO {self.table}
                        (session_id, role, content, content_type, user_id, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            message.session_id,
                            message.role,
                            message.content,
                            message.content_type,
                            message.user_id,
                            message.created_at.isoformat(),
                        ),
                    )
                    
                    # Update user interaction timestamp if user_id provided
                    if message.user_id:
                        self._update_user_interaction(conn, message.user_id)
                    
                    conn.commit()
        except Exception as e:
            logger.error("Failed to append message to PostgreSQL: %s", e)
            raise

    def _update_user_interaction(self, conn: Any, user_id: int) -> None:
        """Update last_interaction_at for user (sync)."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {DBTable.USERS} (user_id, last_interaction_at)
                    VALUES (%s, NOW())
                    ON CONFLICT (user_id) 
                    DO UPDATE SET last_interaction_at = NOW()
                    """,
                    (str(user_id),),
                )
        except Exception as e:
            logger.warning("Failed to update last_interaction_at for user %s: %s", user_id, e)

    def list(self, session_id: str) -> list[StoredMessage]:
        """Get all messages for a session (sync)."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return []
        
        try:
            url = get_postgres_url()
            with psycopg.connect(url) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"""
                        SELECT user_id, session_id, role, content, content_type, created_at
                        FROM {self.table}
                        WHERE session_id = %s
                        ORDER BY created_at
                        """,
                        (session_id,),
                    )
                    rows = cur.fetchall()
                    
                    messages = []
                    for row in rows:
                        created_at = row.get("created_at")
                        try:
                            if isinstance(created_at, str):
                                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                            elif isinstance(created_at, datetime):
                                dt = created_at
                            else:
                                dt = datetime.now(UTC)
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
        except Exception as e:
            logger.error("Failed to list messages for session %s: %s", session_id, e)
            return []

    def list_by_user(self, user_id: int) -> list[StoredMessage]:
        """Get all messages for a user (sync)."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return []
        
        try:
            url = get_postgres_url()
            with psycopg.connect(url) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"""
                        SELECT user_id, session_id, role, content, content_type, created_at
                        FROM {self.table}
                        WHERE user_id = %s
                        ORDER BY created_at
                        """,
                        (user_id,),
                    )
                    rows = cur.fetchall()
                    
                    messages = []
                    for row in rows:
                        created_at = row.get("created_at")
                        try:
                            if isinstance(created_at, str):
                                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                            elif isinstance(created_at, datetime):
                                dt = created_at
                            else:
                                dt = datetime.now(UTC)
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
        except Exception as e:
            logger.error("Failed to list messages for user %s: %s", user_id, e)
            return []

    def delete(self, session_id: str) -> None:
        """Delete all messages for a session (sync)."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return
        
        try:
            url = get_postgres_url()
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self.table} WHERE session_id = %s",
                        (session_id,),
                    )
                    conn.commit()
        except Exception as e:
            logger.error("Failed to delete messages for session %s: %s", session_id, e)

    def delete_by_user(self, user_id: int) -> None:
        """Delete all messages for a user (sync)."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return
        
        try:
            url = get_postgres_url()
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self.table} WHERE user_id = %s",
                        (str(user_id),),
                    )
                    conn.commit()
        except Exception as e:
            logger.error("Failed to delete messages for user %s: %s", user_id, e)


def create_postgres_message_store() -> MessageStore | None:
    """Factory to create PostgreSQL message store if configured."""
    try:
        url = settings.DATABASE_URL or getattr(settings, "POSTGRES_URL", "")
        if not url:
            logger.warning("DATABASE_URL not set, PostgreSQL message store disabled")
            return None
        return PostgresMessageStore()
    except Exception as e:
        logger.error("Failed to create PostgreSQL message store: %s", e)
        return None

