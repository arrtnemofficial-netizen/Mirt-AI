"""PostgreSQL helpers for workers."""

from __future__ import annotations

import logging
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore

from src.services.storage import get_postgres_url

logger = logging.getLogger(__name__)


def get_postgres_connection():
    """Get PostgreSQL connection for workers."""
    if psycopg is None:
        raise RuntimeError("psycopg not installed")
    url = get_postgres_url()
    return psycopg.connect(url)


def call_summarize_inactive_users() -> list[dict[str, Any]]:
    """Call PostgreSQL function summarize_inactive_users()."""
    try:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM summarize_inactive_users()")
                rows = cur.fetchall()
                # Convert to list of dicts
                columns = [desc[0] for desc in cur.description] if cur.description else []
                return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        logger.error("Failed to call summarize_inactive_users: %s", e)
        return []


def get_users_table() -> Any:
    """Get users table query helper."""
    return get_postgres_connection()


def get_messages_table() -> Any:
    """Get messages table query helper."""
    return get_postgres_connection()

