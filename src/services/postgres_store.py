"""PostgreSQL implementation of SessionStore."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from copy import deepcopy
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
    try:
        from psycopg.types.json import Json
    except ImportError:
        Json = None  # type: ignore
except ImportError:
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore
    Json = None  # type: ignore

from src.services.session_store import InMemorySessionStore, SessionStore, _serialize_for_json
from src.agents import ConversationState
from src.conf.config import settings
from src.services.postgres_pool import get_postgres_url

logger = logging.getLogger(__name__)


class PostgresSessionStore:
    """Session storage using PostgreSQL table 'agent_sessions'."""

    def __init__(self, table_name: str | None = None) -> None:
        if table_name is None:
            table_name = getattr(settings, "POSTGRES_TABLE", None) or "agent_sessions"
        self.table_name = table_name
        # In-process fallback store to keep sessions alive when Postgres is down
        self._fallback_store: InMemorySessionStore = InMemorySessionStore()
        self._bg_tasks: set[asyncio.Task] = set()
        logger.info("PostgresSessionStore initialized with table '%s'", self.table_name)

    def _fetch_from_postgres(self, session_id: str) -> ConversationState | None:
        """Fetch session from PostgreSQL (sync)."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return None
        
        try:
            try:
                url = get_postgres_url()
            except ValueError:
                return None
            with psycopg.connect(url) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"SELECT state FROM {self.table_name} WHERE session_id = %s LIMIT 1",
                        (session_id,),
                    )
                    row = cur.fetchone()
                    
                    if row and row.get("state"):
                        state_data = row["state"]
                        if isinstance(state_data, str):
                            try:
                                state_data = json.loads(state_data)
                            except json.JSONDecodeError:
                                return None
                        if isinstance(state_data, dict):
                            return deepcopy(state_data)
                    return None
        except Exception as e:
            logger.error("Failed to fetch session %s from PostgreSQL: %s", session_id, e)
            return None

    def _choose_latest_state(
        self,
        primary_state: ConversationState | None,
        fallback_state: ConversationState,
        session_id: str,
    ) -> ConversationState:
        """Pick the freshest state and keep fallback in sync."""
        if primary_state is None:
            metadata = fallback_state.get("metadata", {})
            metadata.setdefault("session_id", session_id)
            fallback_state["metadata"] = metadata
            return fallback_state

        sup_step = primary_state.get("step_number", 0)
        fb_step = fallback_state.get("step_number", 0)
        chosen = primary_state if sup_step >= fb_step else fallback_state

        metadata = chosen.get("metadata", {})
        metadata.setdefault("session_id", session_id)
        chosen["metadata"] = metadata

        self._fallback_store.save(session_id, chosen)
        return deepcopy(chosen)

    def _in_async_loop(self) -> bool:
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def get(self, session_id: str) -> ConversationState:
        """Return stored state or a fresh empty state."""
        postgres_state = self._fetch_from_postgres(session_id)
        fallback_state = self._fallback_store.get(session_id)
        if not fallback_state:
            fallback_state = self._create_empty_state(session_id)
        return self._choose_latest_state(postgres_state, fallback_state, session_id)

    def _save_to_postgres(self, session_id: str, state: ConversationState) -> bool:
        """Save session to PostgreSQL (sync)."""
        if psycopg is None:
            logger.error("psycopg not installed")
            return False
        
        try:
            # Serialize state to handle LangChain objects
            serialized_state = _serialize_for_json(dict(state))
            state_param = Json(serialized_state) if Json else json.dumps(serialized_state)
            
            try:
                url = get_postgres_url()
            except ValueError:
                return False
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name} (session_id, state, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (session_id) 
                        DO UPDATE SET state = %s, updated_at = NOW()
                        """,
                        (session_id, state_param, state_param),
                    )
                    conn.commit()
                    return True
        except Exception as e:
            logger.error("Failed to save session %s to PostgreSQL: %s", session_id, e)
            return False

    def save(self, session_id: str, state: ConversationState) -> None:
        """Persist the current state for the session."""
        try:
            self._fallback_store.save(session_id, state)
        except Exception as e:
            logger.warning(
                "Failed to save session %s to in-memory fallback store: %s",
                session_id,
                e,
            )

        if not self._in_async_loop():
            self._save_to_postgres(session_id, state)
            return

        async def _save_bg() -> None:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._save_to_postgres, session_id, state),
                    timeout=3.0,
                )
            except TimeoutError:
                logger.warning(
                    "PostgreSQL save timed out (>3s) for session %s; continuing without persistence",
                    session_id,
                )
            except Exception as e:
                logger.debug("PostgreSQL save background task failed for %s: %s", session_id, e)

        task = asyncio.create_task(_save_bg())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def delete(self, session_id: str) -> bool:
        """Delete session state. Returns True if session existed (sync)."""
        existed_in_fallback = self._fallback_store.delete(session_id)
        if psycopg is None:
            logger.error("psycopg not installed")
            return existed_in_fallback
        
        try:
            try:
                url = get_postgres_url()
            except ValueError:
                return existed_in_fallback
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
                    return existed_in_fallback or deleted
        except Exception as e:
            logger.error("Failed to delete session %s from PostgreSQL: %s", session_id, e)
            return existed_in_fallback

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

