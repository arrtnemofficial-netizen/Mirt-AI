"""Shared Supabase client factory used across stores.

This centralises environment-driven creation to avoid duplicated logic in
session, catalog, and message stores.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from src.conf.config import settings


@lru_cache(maxsize=1)
def get_supabase_client() -> Client | None:
    """Return a configured Supabase client or ``None`` when disabled."""
    import logging

    logger = logging.getLogger(__name__)

    if not settings.SUPABASE_URL or not settings.SUPABASE_API_KEY.get_secret_value():
        missing = []
        if not settings.SUPABASE_URL:
            missing.append("SUPABASE_URL")
        if not settings.SUPABASE_API_KEY.get_secret_value():
            missing.append("SUPABASE_API_KEY")
        logger.warning("Supabase disabled - missing env vars: %s", ", ".join(missing))
        return None
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_API_KEY.get_secret_value(),
    )
