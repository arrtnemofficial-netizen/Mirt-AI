from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import psycopg
from src.services.postgres_pool import get_postgres_url


if TYPE_CHECKING:
    from src.agents.pydantic.memory_models import (
        Fact,
        MemoryContext,
        MemoryDecision,
        MemorySummary,
        NewFact,
        UpdateFact,
        UserProfile,
    )


logger = logging.getLogger(__name__)


def _get_memory_models():
    """Lazy import memory models to avoid circular import."""
    from src.agents.pydantic.memory_models import (
        ChildProfile,
        CommerceInfo,
        Fact,
        LogisticsInfo,
        MemoryContext,
        MemoryDecision,
        MemorySummary,
        NewFact,
        StylePreferences,
        UpdateFact,
        UserProfile,
    )

    return {
        "ChildProfile": ChildProfile,
        "CommerceInfo": CommerceInfo,
        "Fact": Fact,
        "LogisticsInfo": LogisticsInfo,
        "MemoryContext": MemoryContext,
        "MemoryDecision": MemoryDecision,
        "MemorySummary": MemorySummary,
        "NewFact": NewFact,
        "StylePreferences": StylePreferences,
        "UpdateFact": UpdateFact,
        "UserProfile": UserProfile,
    }


class MemoryBase:
    """Base class with shared helpers for MemoryService mixins."""

    def __init__(self, client: Any | None = None) -> None:
        # PostgreSQL only - client parameter kept for compatibility but not used
        try:
            get_postgres_url()
            self._enabled = True
        except ValueError:
            self._enabled = False
        self._models = None  # Lazy loaded

        if not self._enabled:
            logger.warning("MemoryService disabled - PostgreSQL URL not available")

    def _get_connection(self):
        """Get PostgreSQL connection."""
        try:
            postgres_url = get_postgres_url()
        except ValueError as e:
            raise RuntimeError("DATABASE_URL not configured") from e
        return psycopg.connect(postgres_url)

    @property
    def models(self):
        """Lazy load memory models to avoid circular import."""
        if self._models is None:
            self._models = _get_memory_models()
        return self._models

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _run_db(self, func, *args, **kwargs):
        """Run blocking DB work in a background thread."""
        return await asyncio.to_thread(func, *args, **kwargs)
