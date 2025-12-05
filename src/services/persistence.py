"""Unified persistence layer for bot state.

This module provides a single source of truth for:
1. Session Store (SupabaseSessionStore or InMemorySessionStore)
2. LangGraph Checkpointer (AsyncPostgresSaver or MemorySaver)

Environment Variables:
- SUPABASE_URL + SUPABASE_API_KEY: For SupabaseSessionStore (HTTP API)
- DATABASE_URL: For AsyncPostgresSaver (Postgres connection)

Architecture:
- Session Store: Manages conversation metadata (session_id, user info, etc.)
- Checkpointer: Manages LangGraph graph state (enables time-travel, persistence)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.conf.config import settings


if TYPE_CHECKING:
    from src.services.session_store import SessionStore


logger = logging.getLogger(__name__)


class PersistenceMode(str, Enum):
    """Persistence modes for the bot."""
    PERSISTENT = "persistent"  # Using Supabase/Postgres
    IN_MEMORY = "in_memory"    # State lost on restart


@dataclass
class PersistenceStatus:
    """Status of persistence layers."""
    session_store_mode: PersistenceMode
    checkpointer_mode: PersistenceMode
    session_store_type: str
    checkpointer_type: str
    missing_env_vars: list[str]
    errors: list[str]
    
    @property
    def is_fully_persistent(self) -> bool:
        return (
            self.session_store_mode == PersistenceMode.PERSISTENT 
            and self.checkpointer_mode == PersistenceMode.PERSISTENT
        )


# =============================================================================
# SESSION STORE FACTORY
# =============================================================================


def create_session_store() -> tuple["SessionStore", PersistenceMode]:
    """
    Create session store with clear logging.
    
    Returns:
        Tuple of (SessionStore instance, mode)
        
    Logic:
    - If SUPABASE_URL and SUPABASE_API_KEY present → SupabaseSessionStore (persistent)
    - Otherwise → InMemorySessionStore (with warning)
    """
    from src.services.session_store import InMemorySessionStore
    from src.services.supabase_store import create_supabase_store
    
    missing_vars = []
    
    # Check required env vars
    if not settings.SUPABASE_URL:
        missing_vars.append("SUPABASE_URL")
    if not settings.SUPABASE_API_KEY.get_secret_value():
        missing_vars.append("SUPABASE_API_KEY")
    
    if missing_vars:
        logger.warning(
            "⚠️ Using InMemorySessionStore - session state will be lost on restart. "
            "Missing env vars: %s",
            ", ".join(missing_vars),
        )
        return InMemorySessionStore(), PersistenceMode.IN_MEMORY
    
    # Try to create Supabase store
    store = create_supabase_store()
    if store is None:
        logger.warning(
            "⚠️ Using InMemorySessionStore - Supabase client creation failed. "
            "Check SUPABASE_URL and SUPABASE_API_KEY."
        )
        return InMemorySessionStore(), PersistenceMode.IN_MEMORY
    
    logger.info("✅ Using SupabaseSessionStore - session state is persistent.")
    return store, PersistenceMode.PERSISTENT


# =============================================================================
# CHECKPOINTER HELPERS
# =============================================================================


def get_database_url() -> str | None:
    """
    Get DATABASE_URL for checkpointer.
    
    Priority:
    1. settings.DATABASE_URL (explicit)
    2. Derive from SUPABASE_URL (if not set)
    """
    database_url = settings.DATABASE_URL
    
    if database_url:
        return database_url
    
    # Auto-derive from Supabase if possible
    supabase_url = settings.SUPABASE_URL
    supabase_key = settings.SUPABASE_API_KEY.get_secret_value() if settings.SUPABASE_API_KEY else None
    
    if supabase_url and supabase_key and "supabase" in supabase_url:
        import re
        match = re.search(r"https://([^.]+)\.supabase", supabase_url)
        if match:
            project_ref = match.group(1)
            derived_url = f"postgresql://postgres:{supabase_key}@db.{project_ref}.supabase.co:5432/postgres"
            logger.info("📌 Derived DATABASE_URL from SUPABASE_URL (project: %s)", project_ref)
            return derived_url
    
    return None


def can_use_persistent_checkpointer() -> bool:
    """Check if persistent checkpointer can be used."""
    return get_database_url() is not None


async def verify_database_connection(database_url: str) -> bool:
    """
    Verify database connection with a simple ping (SELECT 1).
    
    Returns:
        True if connection successful, False otherwise
    """
    try:
        import psycopg
        
        # Use sync connection for simple ping (faster for health check)
        with psycopg.connect(database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                return result is not None and result[0] == 1
    except Exception as e:
        logger.error("❌ Database connection failed: %s", str(e)[:100])
        return False


# =============================================================================
# STARTUP HEALTH CHECK
# =============================================================================


async def init_persistence() -> PersistenceStatus:
    """
    Initialize and verify all persistence layers.
    
    This should be called once at bot startup. It:
    1. Creates session store
    2. Verifies database connection for checkpointer
    3. Returns comprehensive status
    
    Returns:
        PersistenceStatus with detailed info about each layer
    """
    missing_env_vars: list[str] = []
    errors: list[str] = []
    
    # 1. Session Store
    session_store, session_mode = create_session_store()
    
    if session_mode == PersistenceMode.IN_MEMORY:
        if not settings.SUPABASE_URL:
            missing_env_vars.append("SUPABASE_URL")
        if not settings.SUPABASE_API_KEY.get_secret_value():
            missing_env_vars.append("SUPABASE_API_KEY")
    
    # 2. Checkpointer (DATABASE_URL)
    database_url = get_database_url()
    
    if database_url:
        # Verify connection
        if await verify_database_connection(database_url):
            checkpointer_mode = PersistenceMode.PERSISTENT
            checkpointer_type = "AsyncPostgresSaver"
            logger.info("✅ Using AsyncPostgresSaver - checkpoints are persistent.")
        else:
            checkpointer_mode = PersistenceMode.IN_MEMORY
            checkpointer_type = "MemorySaver"
            errors.append("Database connection failed - falling back to MemorySaver")
            logger.warning(
                "⚠️ Using MemorySaver - database connection failed. "
                "Graph state will be lost on restart."
            )
    else:
        checkpointer_mode = PersistenceMode.IN_MEMORY
        checkpointer_type = "MemorySaver"
        if not settings.DATABASE_URL:
            missing_env_vars.append("DATABASE_URL")
        logger.warning(
            "⚠️ Using MemorySaver - DATABASE_URL not set. "
            "Graph state will be lost on restart."
        )
    
    # 3. Summary log
    status = PersistenceStatus(
        session_store_mode=session_mode,
        checkpointer_mode=checkpointer_mode,
        session_store_type=type(session_store).__name__,
        checkpointer_type=checkpointer_type,
        missing_env_vars=missing_env_vars,
        errors=errors,
    )
    
    if status.is_fully_persistent:
        logger.info("🎯 All persistence layers are PERSISTENT - production ready!")
    else:
        logger.warning(
            "⚠️ Some persistence layers are IN_MEMORY - not production ready! "
            "Missing: %s",
            ", ".join(missing_env_vars) if missing_env_vars else "none (check errors)",
        )
    
    return status


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "PersistenceMode",
    "PersistenceStatus",
    "create_session_store",
    "get_database_url",
    "can_use_persistent_checkpointer",
    "verify_database_connection",
    "init_persistence",
]
