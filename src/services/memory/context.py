from __future__ import annotations

import logging

from src.services.memory.base import MemoryBase
from src.services.memory.constants import DEFAULT_FACTS_LIMIT


logger = logging.getLogger(__name__)


class ContextMixin(MemoryBase):
    """Memory context loading and decision application."""

    async def load_memory_context(
        self,
        user_id: str,
        query_embedding: list[float] | None = None,
        facts_limit: int = DEFAULT_FACTS_LIMIT,
    ):
        profile = await self.get_or_create_profile(user_id)

        if query_embedding:
            search_results = await self.search_facts(user_id, query_embedding, limit=facts_limit)
            facts = [f for f, _ in search_results]
        else:
            facts = await self.get_facts(user_id, limit=facts_limit)

        summary = await self.get_user_summary(user_id)

        await self.touch_profile(user_id)

        return self.models["MemoryContext"](
            profile=profile,
            facts=facts,
            summary=summary,
        )

    async def apply_decision(
        self,
        user_id: str,
        decision,
        session_id: str | None = None,
    ) -> dict[str, int]:
        stats = {"stored": 0, "updated": 0, "deleted": 0, "rejected": 0}

        if decision.ignore_messages:
            logger.debug("Decision: ignore messages (no new info)")
            return stats

        for new_fact in decision.new_facts:
            result = await self.store_fact(user_id, new_fact, session_id)
            if result:
                stats["stored"] += 1
            else:
                stats["rejected"] += 1

        for update in decision.updates:
            result = await self.update_fact(update)
            if result:
                stats["updated"] += 1

        for delete in decision.deletes:
            success = await self.deactivate_fact(delete.fact_id, delete.reason)
            if success:
                stats["deleted"] += 1

        if decision.profile_updates:
            await self.update_profile(
                user_id,
                child_profile=decision.profile_updates.get("child_profile"),
                style_preferences=decision.profile_updates.get("style_preferences"),
                logistics=decision.profile_updates.get("logistics"),
                commerce=decision.profile_updates.get("commerce"),
            )

        logger.info(
            "Applied memory decision for user %s: stored=%d, updated=%d, deleted=%d, rejected=%d",
            user_id,
            stats["stored"],
            stats["updated"],
            stats["deleted"],
            stats["rejected"],
        )

        return stats
