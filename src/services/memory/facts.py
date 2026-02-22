from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from src.services.memory.base import MemoryBase
from src.services.memory.constants import DEFAULT_FACTS_LIMIT, MAX_FACTS_LIMIT, TABLE_MEMORIES
from src.services.memory.memory_rules import (
    DEFAULT_MEMORY_RULES,
    FactRejectReason,
    is_fact_expired,
    resolve_ttl_days,
)

if TYPE_CHECKING:
    from uuid import UUID


logger = logging.getLogger(__name__)


class FactsMixin(MemoryBase):
    """Fact CRUD operations and semantic search."""

    async def store_fact(
        self,
        user_id: str,
        fact,
        session_id: str | None = None,
        embedding: list[float] | None = None,
        bypass_gating: bool = False,
    ):
        if not bypass_gating:
            if not getattr(fact, "content", "").strip():
                self._inc_fact_counter("rejected")
                logger.info("Fact rejected: reason=%s", FactRejectReason.INVALID_FACT)
                return None
            if fact.importance < DEFAULT_MEMORY_RULES.min_importance_to_store:
                self._inc_fact_counter("rejected")
                logger.info(
                    "Fact rejected: reason=%s importance=%.2f threshold=%.2f",
                    FactRejectReason.LOW_IMPORTANCE,
                    fact.importance,
                    DEFAULT_MEMORY_RULES.min_importance_to_store,
                )
                return None

        if not self._enabled:
            return None

        now = datetime.now(UTC)
        ttl_days = resolve_ttl_days(fact.fact_type, fact.ttl_days)
        expires_at = None
        if ttl_days:
            expires_at = (now + timedelta(days=ttl_days)).isoformat()

        data = {
            "user_id": user_id,
            "session_id": session_id,
            "content": fact.content,
            "fact_type": fact.fact_type,
            "category": fact.category,
            "importance": fact.importance,
            "surprise": fact.surprise,
            "confidence": 0.8,
            "ttl_days": ttl_days,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "last_accessed_at": now.isoformat(),
            "expires_at": expires_at,
            "is_active": True,
        }

        def _query():
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    if embedding is not None:
                        cur.execute(
                            f"""
                            INSERT INTO {TABLE_MEMORIES}
                            (user_id, session_id, content, fact_type, category,
                             importance, surprise, confidence, ttl_days,
                             created_at, updated_at, last_accessed_at, expires_at,
                             is_active, embedding)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING *
                            """,
                            (
                                data["user_id"],
                                data["session_id"],
                                data["content"],
                                data["fact_type"],
                                data["category"],
                                data["importance"],
                                data["surprise"],
                                data["confidence"],
                                data["ttl_days"],
                                data["created_at"],
                                data["updated_at"],
                                data["last_accessed_at"],
                                data["expires_at"],
                                data["is_active"],
                                embedding,
                            ),
                        )
                    else:
                        cur.execute(
                            f"""
                            INSERT INTO {TABLE_MEMORIES}
                            (user_id, session_id, content, fact_type, category,
                             importance, surprise, confidence, ttl_days,
                             created_at, updated_at, last_accessed_at, expires_at,
                             is_active)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING *
                            """,
                            (
                                data["user_id"],
                                data["session_id"],
                                data["content"],
                                data["fact_type"],
                                data["category"],
                                data["importance"],
                                data["surprise"],
                                data["confidence"],
                                data["ttl_days"],
                                data["created_at"],
                                data["updated_at"],
                                data["last_accessed_at"],
                                data["expires_at"],
                                data["is_active"],
                            ),
                        )
                    row = cur.fetchone()
                conn.commit()
            return row

        try:
            row = await self._run_db(_query)
            if row:
                self._inc_fact_counter("accepted")
                logger.info(
                    "Stored fact for user %s: importance=%.2f, surprise=%.2f",
                    user_id,
                    fact.importance,
                    fact.surprise,
                )
                return self._row_to_fact(row)
            return None
        except Exception as e:
            self._inc_fact_counter("rejected")
            logger.error("Failed to store fact for user %s: %s", user_id, e)
            return None

    async def update_fact(self, update, embedding: list[float] | None = None):
        if not self._enabled:
            return None

        now = datetime.now(UTC).isoformat()
        data: dict[str, Any] = {
            "content": update.new_content,
            "importance": update.importance,
            "surprise": update.surprise,
            "updated_at": now,
            "last_accessed_at": now,
        }
        if embedding is not None:
            data["embedding"] = embedding

        set_clause = ", ".join(f"{key} = %s" for key in data)
        values = list(data.values()) + [str(update.fact_id)]

        def _query():
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"""
                        UPDATE {TABLE_MEMORIES}
                        SET {set_clause},
                            version = COALESCE(version, 0) + 1
                        WHERE id = %s
                        RETURNING *
                        """,
                        values,
                    )
                    row = cur.fetchone()
                conn.commit()
            return row

        try:
            row = await self._run_db(_query)
            if row:
                logger.info("Updated fact %s", update.fact_id)
                return self._row_to_fact(row)
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
    ):
        if not self._enabled:
            return []

        params: list[Any] = [
            user_id,
            min_importance,
            DEFAULT_MEMORY_RULES.min_confidence_to_use,
        ]
        sql = (
            f"SELECT * FROM {TABLE_MEMORIES} "
            "WHERE user_id = %s AND is_active = TRUE AND importance >= %s AND confidence >= %s "
            "AND (expires_at IS NULL OR expires_at > NOW())"
        )
        if categories:
            sql += " AND category = ANY(%s)"
            params.append(categories)
        sql += (
            " ORDER BY importance DESC, confidence DESC, "
            "COALESCE(last_accessed_at, created_at) DESC LIMIT %s"
        )
        params.append(min(limit, MAX_FACTS_LIMIT))

        def _query():
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(sql, params)
                    return cur.fetchall()

        try:
            rows = await self._run_db(_query)
            if rows:
                fact_ids = [row["id"] for row in rows]
                await self._touch_facts(fact_ids)
                return [self._row_to_fact(row) for row in rows]
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
    ):
        if not self._enabled:
            return []

        def _query():
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT * FROM search_memories(%s, %s, %s, %s, %s)",
                        (
                            user_id,
                            query_embedding,
                            min(limit, MAX_FACTS_LIMIT),
                            min_importance,
                            categories,
                        ),
                    )
                    return cur.fetchall()

        try:
            rows = await self._run_db(_query)
            if rows:
                results = []
                for row in rows:
                    reason = self._get_rejection_reason_for_context(row)
                    if reason:
                        logger.debug(
                            "Fact skipped during context read: reason=%s fact_id=%s",
                            reason,
                            row.get("id"),
                        )
                        continue
                    fact = self.models["Fact"](
                        id=row["id"],
                        user_id=user_id,
                        content=row["content"],
                        fact_type=row["fact_type"],
                        category=row["category"],
                        importance=row["importance"],
                        surprise=row["surprise"],
                        confidence=row.get("confidence", 0.8),
                    )
                    similarity = row.get("similarity", 0.0)
                    recency = row.get("last_accessed_at") or row.get("created_at")
                    results.append((fact, similarity, recency))
                results.sort(
                    key=lambda item: (item[1], item[0].importance, item[0].confidence, item[2]),
                    reverse=True,
                )
                return [(fact, similarity) for fact, similarity, _ in results]
            return []
        except Exception as e:
            logger.error("Failed to search facts for user %s: %s", user_id, e)
            return []

    async def deactivate_fact(self, fact_id: UUID, reason: str | None = None) -> bool:
        if not self._enabled:
            return False

        def _query():
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE {TABLE_MEMORIES}
                        SET is_active = FALSE,
                            updated_at = %s
                        WHERE id = %s
                        """,
                        (datetime.now(UTC).isoformat(), str(fact_id)),
                    )
                conn.commit()

        try:
            await self._run_db(_query)
            logger.info("Deactivated fact %s: %s", fact_id, reason)
            return True
        except Exception as e:
            logger.error("Failed to deactivate fact %s: %s", fact_id, e)
            return False

    async def _touch_facts(self, fact_ids: list[str]) -> None:
        if not self._enabled or not fact_ids:
            return

        def _query():
            now = datetime.now(UTC).isoformat()
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE {TABLE_MEMORIES}
                        SET last_accessed_at = %s
                        WHERE id = ANY(%s)
                        """,
                        (now, fact_ids),
                    )
                conn.commit()

        try:
            await self._run_db(_query)
        except Exception as e:
            logger.warning("Failed to touch facts: %s", e)

    def _get_rejection_reason_for_context(self, row: dict[str, Any]) -> FactRejectReason | None:
        if not row.get("is_active", True):
            return FactRejectReason.INACTIVE
        if is_fact_expired(row.get("expires_at")):
            return FactRejectReason.EXPIRED
        if row.get("confidence", 0.0) < DEFAULT_MEMORY_RULES.min_confidence_to_use:
            return FactRejectReason.LOW_CONFIDENCE
        if not row.get("content"):
            return FactRejectReason.INVALID_FACT
        return None

    def _row_to_fact(self, row: dict):
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
