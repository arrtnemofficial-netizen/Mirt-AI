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
    """Return a configured Supabase client or ``None`` when disabled.

    Handles initialization errors gracefully by clearing cache and returning None.
    This allows the system to retry on subsequent calls if configuration is fixed.
    """
    import logging

    logger = logging.getLogger(__name__)

    if not settings.SUPABASE_URL or not settings.SUPABASE_API_KEY.get_secret_value():
        return None

    try:
        return create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_API_KEY.get_secret_value(),
        )
    except Exception as e:
        logger.error(
            "[SUPABASE] Failed to create client: %s. Clearing cache to allow retry.",
            e,
        )
        # Clear cache to allow retry on next call if configuration is fixed
        get_supabase_client.cache_clear()
        return None