"""PostgreSQL implementation of SessionStore."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore

from src.services.session_store import SessionStore, _serialize_for_json
from src.agents import ConversationState
from src.conf.config import settings
from src.services.postgres_pool import get_postgres_url

logger = logging.getLogger(__name__)


class PostgresSessionStore:
    """Session storage using PostgreSQL table 'agent_sessions'."""

    def __init__(self, table_name: str | None = None) -> None:
        if table_name is None:
            table_name = getattr(settings, "POSTGRES_TABLE", None) or settings.SUPABASE_TABLE or "agent_sessions"
        self.table_name = table_name
        logger.info("PostgresSessionStore initialized with table '%s'", self.table_name)

    def _fetch_from_postgres(self, session_id: str) -> ConversationState | None:
        """Fetch session from PostgreSQL (sync)."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return None
        
        try:
            url = get_postgres_url()
            with psycopg.connect(url) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"SELECT state FROM {self.table_name} WHERE session_id = %s LIMIT 1",
                        (session_id,),
                    )
                    row = cur.fetchone()
                    
                    if row and row.get("state"):
                        state_data = row["state"]
                        if isinstance(state_data, dict):
                            return deepcopy(state_data)
                    return None
        except Exception as e:
            logger.error("Failed to fetch session %s from PostgreSQL: %s", session_id, e)
            return None

    def get(self, session_id: str) -> ConversationState:
        """Return stored state or a fresh empty state."""
        postgres_state = self._fetch_from_postgres(session_id)
        
        if postgres_state is None:
            # Create empty state
            return self._create_empty_state(session_id)
        
        # Ensure required metadata fields
        metadata = postgres_state.get("metadata", {})
        metadata.setdefault("session_id", session_id)
        postgres_state["metadata"] = metadata
        
        return deepcopy(postgres_state)

    def _save_to_postgres(self, session_id: str, state: ConversationState) -> bool:
        """Save session to PostgreSQL (sync)."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return False
        
        try:
            # Serialize state to handle LangChain objects
            serialized_state = _serialize_for_json(dict(state))
            
            url = get_postgres_url()
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name} (session_id, state, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (session_id) 
                        DO UPDATE SET state = %s, updated_at = NOW()
                        """,
                        (session_id, json.dumps(serialized_state), json.dumps(serialized_state)),
                    )
                    conn.commit()
                    return True
        except Exception as e:
            logger.error("Failed to save session %s to PostgreSQL: %s", session_id, e)
            return False

    def save(self, session_id: str, state: ConversationState) -> None:
        """Persist the current state for the session."""
        self._save_to_postgres(session_id, state)

    def delete(self, session_id: str) -> bool:
        """Delete session state. Returns True if session existed (sync)."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return False
        
        try:
            url = get_postgres_url()
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self.table_name} WHERE session_id = %s",
                        (session_id,),
                    )
                    conn.commit()
                    deleted = cur.rowcount > 0
                    logger.info(
                        "Deleted session %s from PostgreSQL (existed=%s)",
                        session_id,
                        deleted,
                    )
                    return deleted
        except Exception as e:
            logger.error("Failed to delete session %s from PostgreSQL: %s", session_id, e)
            return False

    def _create_empty_state(self, session_id: str) -> ConversationState:
        """Create a fresh empty state."""
        # Import here to avoid circular dependency
        from src.core.constants import AgentState as StateEnum
        
        return ConversationState(
            messages=[],
            metadata={"session_id": session_id},
            current_state=StateEnum.default(),
        )


def create_postgres_store() -> SessionStore | None:
    """Factory to create PostgreSQL store if configured."""
    try:
        url = settings.DATABASE_URL or getattr(settings, "POSTGRES_URL", "")
        if not url:
            logger.warning("DATABASE_URL not set, PostgreSQL store disabled")
            return None
        return PostgresSessionStore()
    except Exception as e:
        logger.error("Failed to create PostgreSQL store: %s", e)
        return None

