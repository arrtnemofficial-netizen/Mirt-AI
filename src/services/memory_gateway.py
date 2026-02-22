from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from src.services.memory import MemoryService
from src.services.memory.models import Fact, MemoryContext, NewFact

logger = logging.getLogger(__name__)
UTC = timezone.utc


@dataclass(frozen=True)
class PersistenceResult:
    ok: bool
    details: str | None = None


class MemoryGateway(Protocol):
    async def upsert_fact(
        self,
        session_id: str,
        fact: NewFact,
        importance: float,
        confidence: float,
        source: str,
    ) -> PersistenceResult: ...

    async def fetch_context(
        self,
        session_id: str,
        limit: int,
        min_importance: float,
    ) -> MemoryContext | None: ...

    async def decay_or_cleanup(self, now_utc: datetime) -> PersistenceResult: ...


class PostgresMemoryGateway:
    """Production adapter backed by MemoryService/Postgres."""

    def __init__(self, memory_service: MemoryService | None = None) -> None:
        self._memory_service = memory_service or MemoryService()

    @property
    def enabled(self) -> bool:
        return self._memory_service.enabled

    async def upsert_fact(
        self,
        session_id: str,
        fact: NewFact,
        importance: float,
        confidence: float,
        source: str,
    ) -> PersistenceResult:
        if not self.enabled:
            return PersistenceResult(ok=False, details="memory_disabled")

        fact_for_storage = fact.model_copy(update={"importance": importance})

        try:
            stored = await self._memory_service.store_fact(
                user_id=session_id,
                fact=fact_for_storage,
                session_id=source,
                bypass_gating=True,
            )
            if stored:
                return PersistenceResult(ok=True)
            return PersistenceResult(ok=False, details="rejected_or_not_stored")
        except Exception as exc:  # noqa: BLE001
            logger.error("Memory upsert failed for session=%s: %s", session_id, exc)
            return PersistenceResult(ok=False, details="persistence_error")

    async def fetch_context(
        self,
        session_id: str,
        limit: int,
        min_importance: float,
    ) -> MemoryContext | None:
        if not self.enabled:
            return None

        try:
            profile = await self._memory_service.get_or_create_profile(session_id)
            facts = await self._memory_service.get_facts(
                user_id=session_id,
                limit=limit,
                min_importance=min_importance,
            )
            summary = await self._memory_service.get_user_summary(session_id)
            await self._memory_service.touch_profile(session_id)
            return MemoryContext(profile=profile, facts=facts, summary=summary)
        except Exception as exc:  # noqa: BLE001
            logger.error("Memory fetch_context failed for session=%s: %s", session_id, exc)
            return None

    async def decay_or_cleanup(self, now_utc: datetime) -> PersistenceResult:
        _ = now_utc.astimezone(UTC)
        if not self.enabled:
            return PersistenceResult(ok=False, details="memory_disabled")

        try:
            decay_count = await self._memory_service.apply_time_decay()
            cleanup_count = await self._memory_service.cleanup_expired()
            return PersistenceResult(ok=True, details=f"decay={decay_count},cleanup={cleanup_count}")
        except Exception as exc:  # noqa: BLE001
            logger.error("Memory decay_or_cleanup failed: %s", exc)
            return PersistenceResult(ok=False, details="persistence_error")


class InMemoryMemoryGateway:
    """Test adapter: deterministic in-memory persistence."""

    def __init__(self) -> None:
        self._facts: dict[str, list[Fact]] = {}

    async def upsert_fact(
        self,
        session_id: str,
        fact: NewFact,
        importance: float,
        confidence: float,
        source: str,
    ) -> PersistenceResult:
        entry = Fact(
            user_id=session_id,
            session_id=source,
            content=fact.content,
            fact_type=fact.fact_type,
            category=fact.category,
            importance=importance,
            surprise=fact.surprise,
            confidence=confidence,
            ttl_days=fact.ttl_days,
        )
        self._facts.setdefault(session_id, []).append(entry)
        return PersistenceResult(ok=True)

    async def fetch_context(
        self,
        session_id: str,
        limit: int,
        min_importance: float,
    ) -> MemoryContext | None:
        facts = [
            fact
            for fact in self._facts.get(session_id, [])
            if fact.importance >= min_importance and fact.is_active
        ]
        facts = sorted(facts, key=lambda item: item.importance, reverse=True)[:limit]
        return MemoryContext(profile=None, facts=facts, summary=None)

    async def decay_or_cleanup(self, now_utc: datetime) -> PersistenceResult:
        _ = now_utc.astimezone(UTC)
        return PersistenceResult(ok=True, details="noop")


_gateway: MemoryGateway = PostgresMemoryGateway()


def get_memory_gateway() -> MemoryGateway:
    return _gateway


def set_memory_gateway(gateway: MemoryGateway) -> None:
    global _gateway
    _gateway = gateway
