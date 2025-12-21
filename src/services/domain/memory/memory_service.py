"""
Memory Service - AGI-Style Memory Layer (Titans-like).
========================================================
CRUD operations для 3-рівневої архітектури памʼяті:
  1. Profiles (Persistent Memory)
  2. Memories/Facts (Fluid Memory)
  3. Summaries (Compressed Memory)

Ключова логіка:
- Gating: importance >= 0.6 AND surprise >= 0.4 для запису
- Semantic search через pgvector
- Profile merge для JSONB полів
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.services.infra.supabase_client import get_supabase_client


if TYPE_CHECKING:
    from uuid import UUID

    from supabase import Client

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


# =============================================================================
# CONSTANTS
# =============================================================================

# Gating thresholds (Titans-like)
MIN_IMPORTANCE_TO_STORE = 0.6
MIN_SURPRISE_TO_STORE = 0.4

# Query limits
DEFAULT_FACTS_LIMIT = 10
MAX_FACTS_LIMIT = 50

# Table names
TABLE_PROFILES = "mirt_profiles"
TABLE_MEMORIES = "mirt_memories"
TABLE_SUMMARIES = "mirt_memory_summaries"


# =============================================================================
# MEMORY SERVICE
# =============================================================================


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


class MemoryService:
    """
    Service для роботи з Titans-like памʼяттю.

    Provides:
    - Profile CRUD (Persistent Memory)
    - Facts CRUD with gating (Fluid Memory)
    - Summaries CRUD (Compressed Memory)
    - Semantic search
    - Memory context loading
    """

    def __init__(self, client: Client | None = None) -> None:
        self.client = client or get_supabase_client()
        self._enabled = self.client is not None
        self._models = None  # Lazy loaded

        if not self._enabled:
            logger.warning("MemoryService disabled - Supabase client not available")

    @property
    def models(self):
        """Lazy load memory models to avoid circular import."""
        if self._models is None:
            self._models = _get_memory_models()
        return self._models

    @property
    def enabled(self) -> bool:
        return self._enabled

    # =========================================================================
    # PROFILE OPERATIONS (Persistent Memory)
    # =========================================================================

    async def get_profile(self, user_id: str) -> UserProfile | None:
        """
        Завантажити профіль користувача.

        Args:
            user_id: External ID (Telegram/ManyChat/Instagram)

        Returns:
            UserProfile або None якщо не знайдено
        """
        if not self._enabled:
            return None

        try:
            response = (
                self.client.table(TABLE_PROFILES)
                .select("*")
                .eq("user_id", user_id)
                .single()
                .execute()
            )

            if not response.data:
                return None

            return self._row_to_profile(response.data)

        except Exception as e:
            # Handle "no rows returned" gracefully
            if "0 rows" in str(e).lower():
                return None
            logger.error("Failed to get profile for user %s: %s", user_id, e)
            return None

    async def get_or_create_profile(self, user_id: str) -> UserProfile:
        """
        Отримати профіль або створити новий.

        Args:
            user_id: External ID

        Returns:
            Existing or new UserProfile
        """
        existing = await self.get_profile(user_id)
        if existing:
            return existing

        # Create new profile
        return await self.create_profile(user_id)

    async def create_profile(self, user_id: str) -> UserProfile:
        """
        Створити новий профіль.

        Args:
            user_id: External ID

        Returns:
            Created UserProfile
        """
        if not self._enabled:
            return self.models["UserProfile"](user_id=user_id)

        try:
            now = datetime.now(UTC).isoformat()
            data = {
                "user_id": user_id,
                "child_profile": {},
                "style_preferences": {},
                "logistics": {},
                "commerce": {},
                "created_at": now,
                "updated_at": now,
                "last_seen_at": now,
            }

            response = self.client.table(TABLE_PROFILES).insert(data).execute()

            if response.data:
                logger.info("Created profile for user %s", user_id)
                return self._row_to_profile(response.data[0])

            return self.models["UserProfile"](user_id=user_id)

        except Exception as e:
            logger.error("Failed to create profile for user %s: %s", user_id, e)
            return self.models["UserProfile"](user_id=user_id)

    async def update_profile(
        self,
        user_id: str,
        child_profile: dict | None = None,
        style_preferences: dict | None = None,
        logistics: dict | None = None,
        commerce: dict | None = None,
    ) -> UserProfile | None:
        """
        Оновити профіль (merge з існуючими даними).

        Args:
            user_id: External ID
            child_profile: Partial update for child_profile
            style_preferences: Partial update for style_preferences
            logistics: Partial update for logistics
            commerce: Partial update for commerce

        Returns:
            Updated UserProfile або None при помилці
        """
        if not self._enabled:
            return None

        try:
            # Get current profile
            current = await self.get_profile(user_id)
            if not current:
                current = await self.create_profile(user_id)

            # Merge updates
            updates: dict[str, Any] = {
                "updated_at": datetime.now(UTC).isoformat(),
                "last_seen_at": datetime.now(UTC).isoformat(),
            }

            if child_profile:
                merged = {**current.child_profile.model_dump(), **child_profile}
                updates["child_profile"] = merged

            if style_preferences:
                merged = {**current.style_preferences.model_dump(), **style_preferences}
                # Merge lists (append unique values)
                for key in [
                    "favorite_models",
                    "favorite_colors",
                    "avoided_colors",
                    "preferred_styles",
                    "fabric_preferences",
                ]:
                    if key in style_preferences and key in current.style_preferences.model_dump():
                        existing = current.style_preferences.model_dump().get(key, [])
                        new = style_preferences.get(key, [])
                        merged[key] = list(set(existing + new))
                updates["style_preferences"] = merged

            if logistics:
                merged = {**current.logistics.model_dump(), **logistics}
                updates["logistics"] = merged

            if commerce:
                merged = {**current.commerce.model_dump(), **commerce}
                updates["commerce"] = merged

            # Apply update
            response = (
                self.client.table(TABLE_PROFILES).update(updates).eq("user_id", user_id).execute()
            )

            if response.data:
                logger.info("Updated profile for user %s", user_id)
                return self._row_to_profile(response.data[0])

            return current

        except Exception as e:
            logger.error("Failed to update profile for user %s: %s", user_id, e)
            return None

    async def touch_profile(self, user_id: str) -> None:
        """Оновити last_seen_at для профілю."""
        if not self._enabled:
            return

        try:
            self.client.table(TABLE_PROFILES).update(
                {"last_seen_at": datetime.now(UTC).isoformat()}
            ).eq("user_id", user_id).execute()
        except Exception as e:
            logger.warning("Failed to touch profile for user %s: %s", user_id, e)

    def _row_to_profile(self, row: dict) -> UserProfile:
        """Convert DB row to UserProfile.

        SENIOR TIP: We use self.models for lazy import to avoid circular imports.
        The models are only loaded when first accessed, not at module load time.
        """
        m = self.models  # Lazy load models
        return m["UserProfile"](
            user_id=row.get("user_id", ""),
            child_profile=m["ChildProfile"](**row.get("child_profile", {})),
            style_preferences=m["StylePreferences"](**row.get("style_preferences", {})),
            logistics=m["LogisticsInfo"](**row.get("logistics", {})),
            commerce=m["CommerceInfo"](**row.get("commerce", {})),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            last_seen_at=row.get("last_seen_at"),
            completeness_score=row.get("completeness_score", 0.0),
        )

    # =========================================================================
    # MEMORY/FACTS OPERATIONS (Fluid Memory)
    # =========================================================================

    async def store_fact(
        self,
        user_id: str,
        fact: NewFact,
        session_id: str | None = None,
        embedding: list[float] | None = None,
        bypass_gating: bool = False,
    ) -> Fact | None:
        """
        Зберегти новий факт (з gating перевіркою).

        Gating rule: importance >= 0.6 AND surprise >= 0.4

        Args:
            user_id: External ID
            fact: NewFact to store
            session_id: Optional session ID
            embedding: Optional vector embedding
            bypass_gating: Bypass importance/surprise check

        Returns:
            Stored Fact або None якщо відхилено gating
        """
        # GATING CHECK (Titans-like)
        if not bypass_gating:
            if fact.importance < MIN_IMPORTANCE_TO_STORE:
                logger.debug(
                    "Fact rejected by gating: importance=%.2f < %.2f",
                    fact.importance,
                    MIN_IMPORTANCE_TO_STORE,
                )
                return None
            if fact.surprise < MIN_SURPRISE_TO_STORE:
                logger.debug(
                    "Fact rejected by gating: surprise=%.2f < %.2f",
                    fact.surprise,
                    MIN_SURPRISE_TO_STORE,
                )
                return None

        if not self._enabled:
            return None

        try:
            now = datetime.now(UTC)
            expires_at = None
            if fact.ttl_days:
                expires_at = (now + timedelta(days=fact.ttl_days)).isoformat()

            data = {
                "user_id": user_id,
                "session_id": session_id,
                "content": fact.content,
                "fact_type": fact.fact_type,
                "category": fact.category,
                "importance": fact.importance,
                "surprise": fact.surprise,
                "confidence": 0.8,  # Default confidence
                "ttl_days": fact.ttl_days,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "last_accessed_at": now.isoformat(),
                "expires_at": expires_at,
                "is_active": True,
            }

            if embedding:
                data["embedding"] = embedding

            response = self.client.table(TABLE_MEMORIES).insert(data).execute()

            if response.data:
                logger.info(
                    "Stored fact for user %s: importance=%.2f, surprise=%.2f",
                    user_id,
                    fact.importance,
                    fact.surprise,
                )
                return self._row_to_fact(response.data[0])

            return None

        except Exception as e:
            logger.error("Failed to store fact for user %s: %s", user_id, e)
            return None

    async def update_fact(
        self,
        update: UpdateFact,
        embedding: list[float] | None = None,
    ) -> Fact | None:
        """
        Оновити існуючий факт.

        Args:
            update: UpdateFact with new content
            embedding: Optional new embedding

        Returns:
            Updated Fact або None при помилці
        """
        if not self._enabled:
            return None

        try:
            now = datetime.now(UTC).isoformat()

            data: dict[str, Any] = {
                "content": update.new_content,
                "importance": update.importance,
                "surprise": update.surprise,
                "updated_at": now,
                "last_accessed_at": now,
            }

            if embedding:
                data["embedding"] = embedding

            # Increment version
            data["version"] = (
                self.client.table(TABLE_MEMORIES)
                .select("version")
                .eq("id", str(update.fact_id))
                .single()
                .execute()
                .data.get("version", 0)
                + 1
            )

            response = (
                self.client.table(TABLE_MEMORIES)
                .update(data)
                .eq("id", str(update.fact_id))
                .execute()
            )

            if response.data:
                logger.info("Updated fact %s", update.fact_id)
                return self._row_to_fact(response.data[0])

            return None

        except Exception as e:
            logger.error("Failed to update fact %s: %s", update.fact_id, e)
            return None

    async def get_facts(
        self,
        user_id: str,
        limit: int = DEFAULT_FACTS_LIMIT,
        categories: list[str] | None = None,
        min_importance: float = 0.3,
    ) -> list[Fact]:
        """
        Отримати факти для користувача.

        Args:
            user_id: External ID
            limit: Max facts to return
            categories: Filter by categories
            min_importance: Minimum importance threshold

        Returns:
            List of Facts sorted by importance
        """
        if not self._enabled:
            return []

        try:
            query = (
                self.client.table(TABLE_MEMORIES)
                .select("*")
                .eq("user_id", user_id)
                .eq("is_active", True)
                .gte("importance", min_importance)
                .order("importance", desc=True)
                .limit(min(limit, MAX_FACTS_LIMIT))
            )

            if categories:
                query = query.in_("category", categories)

            response = query.execute()

            if response.data:
                # Update last_accessed_at for retrieved facts
                fact_ids = [row["id"] for row in response.data]
                await self._touch_facts(fact_ids)

                return [self._row_to_fact(row) for row in response.data]

            return []

        except Exception as e:
            logger.error("Failed to get facts for user %s: %s", user_id, e)
            return []

    async def search_facts(
        self,
        user_id: str,
        query_embedding: list[float],
        limit: int = DEFAULT_FACTS_LIMIT,
        min_importance: float = 0.3,
        categories: list[str] | None = None,
    ) -> list[tuple[Fact, float]]:
        """
        Semantic search через pgvector.

        Args:
            user_id: External ID
            query_embedding: Query vector (1536 dims)
            limit: Max results
            min_importance: Minimum importance
            categories: Filter by categories

        Returns:
            List of (Fact, similarity_score) tuples
        """
        if not self._enabled:
            return []

        try:
            # Use RPC function for vector search
            params = {
                "p_user_id": user_id,
                "p_query_embedding": query_embedding,
                "p_limit": min(limit, MAX_FACTS_LIMIT),
                "p_min_importance": min_importance,
                "p_categories": categories,
            }

            response = self.client.rpc("search_memories", params).execute()

            if response.data:
                results = []
                for row in response.data:
                    fact = self.models["Fact"](
                        id=row["id"],
                        user_id=user_id,
                        content=row["content"],
                        fact_type=row["fact_type"],
                        category=row["category"],
                        importance=row["importance"],
                        surprise=row["surprise"],
                    )
                    similarity = row.get("similarity", 0.0)
                    results.append((fact, similarity))
                return results

            return []

        except Exception as e:
            logger.error("Failed to search facts for user %s: %s", user_id, e)
            return []

    async def deactivate_fact(self, fact_id: UUID, reason: str | None = None) -> bool:
        """Деактивувати факт (soft delete)."""
        if not self._enabled:
            return False

        try:
            self.client.table(TABLE_MEMORIES).update(
                {
                    "is_active": False,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ).eq("id", str(fact_id)).execute()

            logger.info("Deactivated fact %s: %s", fact_id, reason)
            return True

        except Exception as e:
            logger.error("Failed to deactivate fact %s: %s", fact_id, e)
            return False

    async def _touch_facts(self, fact_ids: list[str]) -> None:
        """Update last_accessed_at for facts."""
        if not self._enabled or not fact_ids:
            return

        try:
            now = datetime.now(UTC).isoformat()
            for fact_id in fact_ids:
                self.client.table(TABLE_MEMORIES).update({"last_accessed_at": now}).eq(
                    "id", fact_id
                ).execute()
        except Exception as e:
            logger.warning("Failed to touch facts: %s", e)

    def _row_to_fact(self, row: dict) -> Fact:
        """Convert DB row to Fact."""
        return self.models["Fact"](
            id=row.get("id"),
            user_id=row.get("user_id", ""),
            session_id=row.get("session_id"),
            content=row.get("content", ""),
            fact_type=row.get("fact_type", "preference"),
            category=row.get("category", "general"),
            importance=row.get("importance", 0.5),
            surprise=row.get("surprise", 0.5),
            confidence=row.get("confidence", 0.8),
            ttl_days=row.get("ttl_days"),
            created_at=row.get("created_at"),
            last_accessed_at=row.get("last_accessed_at"),
            is_active=row.get("is_active", True),
        )

    # =========================================================================
    # SUMMARY OPERATIONS (Compressed Memory)
    # =========================================================================

    async def get_user_summary(self, user_id: str) -> MemorySummary | None:
        """Отримати актуальний summary для користувача."""
        if not self._enabled:
            return None

        try:
            response = (
                self.client.table(TABLE_SUMMARIES)
                .select("*")
                .eq("user_id", user_id)
                .eq("summary_type", "user")
                .eq("is_current", True)
                .single()
                .execute()
            )

            if response.data:
                return self._row_to_summary(response.data)

            return None

        except Exception as e:
            if "0 rows" not in str(e).lower():
                logger.error("Failed to get summary for user %s: %s", user_id, e)
            return None

    async def save_summary(
        self,
        user_id: str,
        summary_text: str,
        key_facts: list[str] | None = None,
        facts_count: int = 0,
    ) -> MemorySummary | None:
        """
        Зберегти summary (замінює попередній).

        Args:
            user_id: External ID
            summary_text: Summary text
            key_facts: Key facts list
            facts_count: Number of facts summarized

        Returns:
            Created MemorySummary
        """
        if not self._enabled:
            return None

        try:
            # Deactivate old summaries
            self.client.table(TABLE_SUMMARIES).update(
                {
                    "is_current": False,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ).eq("user_id", user_id).eq("summary_type", "user").execute()

            # Create new summary
            now = datetime.now(UTC).isoformat()
            data = {
                "user_id": user_id,
                "summary_type": "user",
                "summary_text": summary_text,
                "key_facts": key_facts or [],
                "facts_count": facts_count,
                "created_at": now,
                "updated_at": now,
                "is_current": True,
            }

            response = self.client.table(TABLE_SUMMARIES).insert(data).execute()

            if response.data:
                logger.info("Saved summary for user %s", user_id)
                return self._row_to_summary(response.data[0])

            return None

        except Exception as e:
            logger.error("Failed to save summary for user %s: %s", user_id, e)
            return None

    def _row_to_summary(self, row: dict) -> MemorySummary:
        """Convert DB row to MemorySummary."""
        return self.models["MemorySummary"](
            summary_type=row.get("summary_type", "user"),
            summary_text=row.get("summary_text", ""),
            key_facts=row.get("key_facts", []),
            facts_count=row.get("facts_count", 0),
            is_current=row.get("is_current", True),
        )

    # =========================================================================
    # MEMORY CONTEXT (Combined Loading)
    # =========================================================================

    async def load_memory_context(
        self,
        user_id: str,
        query_embedding: list[float] | None = None,
        facts_limit: int = DEFAULT_FACTS_LIMIT,
    ) -> MemoryContext:
        """
        Завантажити повний контекст памʼяті для агента.

        Це головний метод для використання в memory_context_node.

        Args:
            user_id: External ID
            query_embedding: Optional query for semantic search
            facts_limit: Max facts to load

        Returns:
            MemoryContext з profile, facts, summary
        """
        # Load profile
        profile = await self.get_or_create_profile(user_id)

        # Load facts (semantic search if embedding provided)
        facts: list[Fact] = []
        if query_embedding:
            search_results = await self.search_facts(user_id, query_embedding, limit=facts_limit)
            facts = [f for f, _ in search_results]
        else:
            facts = await self.get_facts(user_id, limit=facts_limit)

        # Load summary
        summary = await self.get_user_summary(user_id)

        # Touch profile (update last_seen_at)
        await self.touch_profile(user_id)

        return self.models["MemoryContext"](
            profile=profile,
            facts=facts,
            summary=summary,
        )

    # =========================================================================
    # APPLY MEMORY DECISION
    # =========================================================================

    async def apply_decision(
        self,
        user_id: str,
        decision: MemoryDecision,
        session_id: str | None = None,
    ) -> dict[str, int]:
        """
        Застосувати рішення MemoryAgent.

        Args:
            user_id: External ID
            decision: MemoryDecision from MemoryAgent
            session_id: Optional session ID

        Returns:
            Stats: {"stored": N, "updated": M, "deleted": K, "rejected": R}
        """
        stats = {"stored": 0, "updated": 0, "deleted": 0, "rejected": 0}

        if decision.ignore_messages:
            logger.debug("Decision: ignore messages (no new info)")
            return stats

        # Store new facts (with gating)
        for new_fact in decision.new_facts:
            result = await self.store_fact(user_id, new_fact, session_id)
            if result:
                stats["stored"] += 1
            else:
                stats["rejected"] += 1

        # Update existing facts
        for update in decision.updates:
            result = await self.update_fact(update)
            if result:
                stats["updated"] += 1

        # Delete facts
        for delete in decision.deletes:
            success = await self.deactivate_fact(delete.fact_id, delete.reason)
            if success:
                stats["deleted"] += 1

        # Update profile
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

    # =========================================================================
    # MAINTENANCE (Background Tasks)
    # =========================================================================

    async def apply_time_decay(self) -> int:
        """
        Застосувати time decay до старих фактів.

        Returns:
            Number of affected rows
        """
        if not self._enabled:
            return 0

        try:
            response = self.client.rpc("apply_memory_decay").execute()
            affected = response.data if isinstance(response.data, int) else 0
            logger.info("Applied time decay to %d memories", affected)
            return affected
        except Exception as e:
            logger.error("Failed to apply time decay: %s", e)
            return 0

    async def cleanup_expired(self) -> int:
        """
        Видалити expired факти.

        Returns:
            Number of deleted rows
        """
        if not self._enabled:
            return 0

        try:
            now = datetime.now(UTC).isoformat()

            response = (
                self.client.table(TABLE_MEMORIES)
                .update({"is_active": False})
                .lt("expires_at", now)
                .eq("is_active", True)
                .execute()
            )

            count = len(response.data) if response.data else 0
            logger.info("Cleaned up %d expired memories", count)
            return count

        except Exception as e:
            logger.error("Failed to cleanup expired: %s", e)
            return 0


# =============================================================================
# FACTORY
# =============================================================================


def create_memory_service() -> MemoryService:
    """Factory function for MemoryService."""
    return MemoryService()
