"""Shared Supabase client factory used across stores.

This centralises environment-driven creation to avoid duplicated logic in
session, catalog, and message stores.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from supabase import Client, create_client

from src.conf.config import settings


@lru_cache(maxsize=1)
def get_supabase_client() -> Optional[Client]:
    """Return a configured Supabase client or ``None`` when disabled."""

    if not settings.SUPABASE_URL or not settings.SUPABASE_API_KEY.get_secret_value():
        return None
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_API_KEY.get_secret_value(),
    )

