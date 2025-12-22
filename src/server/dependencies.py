"""FastAPI dependency injection module.

This module provides lazy-initialized dependencies for the FastAPI application,
replacing global singletons with proper DI pattern.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from aiogram import Bot, Dispatcher
from fastapi import Depends

from src.bot.telegram_bot import build_bot, build_dispatcher
from src.conf.config import Settings, get_settings
from src.integrations.manychat.async_service import ManyChatAsyncService, get_manychat_async_service
from src.services.infra.message_store import MessageStore, create_message_store
from src.services.infra.session_store import InMemorySessionStore, SessionStore
from src.services.infra.supabase_store import create_supabase_store


# Type aliases for cleaner dependency injection
SettingsDep = Annotated[Settings, Depends(get_settings)]


@lru_cache(maxsize=1)
def get_session_store() -> SessionStore:
    """Get or create the session store (Supabase or in-memory fallback)."""
    supabase_store = create_supabase_store()
    if supabase_store:
        return supabase_store
    return InMemorySessionStore()


@lru_cache(maxsize=1)
def get_message_store() -> MessageStore:
    """Get or create the message store."""
    return create_message_store()


@lru_cache(maxsize=1)
def get_bot() -> Bot:
    """Get or create the Telegram bot instance."""
    return build_bot()


def get_dispatcher(
    store: Annotated[SessionStore, Depends(get_session_store)],
    message_store: Annotated[MessageStore, Depends(get_message_store)],
) -> Dispatcher:
    """Create the Telegram dispatcher with injected dependencies."""
    return build_dispatcher(store, message_store)


def get_manychat_service(
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> ManyChatAsyncService:
    """Create the ManyChat async service (shared for sync/push flows)."""
    return get_manychat_async_service(store)


# Cached instances for reuse across requests
_dispatcher_instance: Dispatcher | None = None
_manychat_service_instance: ManyChatAsyncService | None = None


def get_cached_dispatcher() -> Dispatcher:
    """Get cached dispatcher instance (for webhook handling)."""
    global _dispatcher_instance
    if _dispatcher_instance is None:
        store = get_session_store()
        message_store = get_message_store()
        _dispatcher_instance = build_dispatcher(store, message_store)
    return _dispatcher_instance


def get_cached_manychat_service() -> ManyChatAsyncService:
    """Get cached ManyChat service instance."""
    global _manychat_service_instance
    if _manychat_service_instance is None:
        store = get_session_store()
        _manychat_service_instance = get_manychat_async_service(store)
    return _manychat_service_instance


# Type aliases for endpoint injection
SessionStoreDep = Annotated[SessionStore, Depends(get_session_store)]
MessageStoreDep = Annotated[MessageStore, Depends(get_message_store)]
BotDep = Annotated[Bot, Depends(get_bot)]
DispatcherDep = Annotated[Dispatcher, Depends(get_cached_dispatcher)]
ManychatServiceDep = Annotated[ManyChatAsyncService, Depends(get_cached_manychat_service)]


def reset_dependencies() -> None:
    """Reset all cached dependencies (useful for testing)."""
    global _dispatcher_instance, _manychat_service_instance

    _dispatcher_instance = None
    _manychat_service_instance = None

    # Clear lru_cache
    get_session_store.cache_clear()
    get_message_store.cache_clear()
    get_bot.cache_clear()
