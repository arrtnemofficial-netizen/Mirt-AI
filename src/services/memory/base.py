from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

import psycopg

from src.services.storage import get_postgres_url


logger = logging.getLogger(__name__)


def _get_memory_models():
    """Lazy import memory models (now in services/memory/models.py)."""
    from src.services.memory.models import (
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
        self._fact_counters: defaultdict[str, int] = defaultdict(int)

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

    def _inc_fact_counter(self, counter_name: str, value: int = 1) -> None:
        self._fact_counters[counter_name] += value
        logger.info("metric.memory.%s=%d", counter_name, self._fact_counters[counter_name])
