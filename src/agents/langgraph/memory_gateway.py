from __future__ import annotations

import logging
from typing import Any

from src.agents.pydantic.memory_agent import extract_quick_facts
from src.services.memory import MemoryService
from src.services.memory.models import NewFact

logger = logging.getLogger(__name__)


class MemoryGateway:
    """Best-effort adapter між LangGraph nodes та MemoryService."""

    @staticmethod
    async def fetch_context(
        session_id: str,
        *,
        user_id: str | None,
        facts_limit: int = 5,
    ) -> dict[str, Any]:
        if not user_id:
            return {"storage_available": False, "reason": "missing_user_id"}

        try:
            memory_service = MemoryService()
            if not memory_service.enabled:
                return {"storage_available": False, "reason": "disabled"}

            context = await memory_service.load_memory_context(user_id=user_id, facts_limit=facts_limit)
            return {
                "storage_available": True,
                "profile": context.profile,
                "facts": context.facts,
                "prompt": context.to_prompt_block() if not context.is_empty() else None,
            }
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("[SESSION %s] Memory fetch failed: %s", session_id, exc)
            return {"storage_available": False, "reason": type(exc).__name__}

    @staticmethod
    async def upsert_fact(
        session_id: str,
        *,
        user_id: str | None,
        content: str,
        fact_type: str = "preference",
        category: str = "preferences",
        importance: float = 0.7,
        surprise: float = 0.5,
    ) -> bool:
        if not user_id or not content.strip():
            return False

        try:
            memory_service = MemoryService()
            if not memory_service.enabled:
                return False

            result = await memory_service.store_fact(
                user_id=user_id,
                session_id=session_id,
                fact=NewFact(
                    content=content.strip(),
                    fact_type=fact_type,
                    category=category,
                    importance=importance,
                    surprise=surprise,
                    ttl_days=None,
                ),
            )
            return result is not None
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("[SESSION %s] Memory upsert failed: %s", session_id, exc)
            return False


async def upsert_facts_from_text(
    *,
    session_id: str,
    user_id: str | None,
    text: str,
) -> int:
    """Виділяє quick facts і best-effort зберігає їх перед фінальним return node."""
    if not text.strip():
        return 0

    stored = 0
    for fact in extract_quick_facts(text):
        ok = await MemoryGateway.upsert_fact(
            session_id=session_id,
            user_id=user_id,
            content=fact.get("content", ""),
            fact_type=fact.get("fact_type", "preference"),
            category=fact.get("category", "preferences"),
            importance=0.85,
            surprise=0.55,
        )
        if ok:
            stored += 1
    return stored
