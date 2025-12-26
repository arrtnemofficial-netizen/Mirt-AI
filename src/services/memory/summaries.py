from __future__ import annotations

import logging
from datetime import UTC, datetime

from psycopg.rows import dict_row

from src.services.memory.base import MemoryBase
from src.services.memory.constants import TABLE_SUMMARIES


logger = logging.getLogger(__name__)


class SummariesMixin(MemoryBase):
    """Summary CRUD operations."""

    async def get_user_summary(self, user_id: str):
        if not self._enabled:
            return None

        def _query():
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"""
                        SELECT * FROM {TABLE_SUMMARIES}
                        WHERE user_id = %s
                          AND summary_type = %s
                          AND is_current = TRUE
                        LIMIT 1
                        """,
                        (user_id, "user"),
                    )
                    return cur.fetchone()

        try:
            row = await self._run_db(_query)
            if row:
                return self._row_to_summary(row)
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
    ):
        if not self._enabled:
            return None

        now = datetime.now(UTC).isoformat()

        def _query():
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"""
                        UPDATE {TABLE_SUMMARIES}
                        SET is_current = FALSE,
                            updated_at = %s
                        WHERE user_id = %s
                          AND summary_type = %s
                        """,
                        (now, user_id, "user"),
                    )

                    cur.execute(
                        f"""
                        INSERT INTO {TABLE_SUMMARIES}
                        (user_id, summary_type, summary_text, key_facts, facts_count,
                         created_at, updated_at, is_current)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING *
                        """,
                        (
                            user_id,
                            "user",
                            summary_text,
                            key_facts or [],
                            facts_count,
                            now,
                            now,
                            True,
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
            return row

        try:
            row = await self._run_db(_query)
            if row:
                logger.info("Saved summary for user %s", user_id)
                return self._row_to_summary(row)
            return None
        except Exception as e:
            logger.error("Failed to save summary for user %s: %s", user_id, e)
            return None

    def _row_to_summary(self, row: dict):
        return self.models["MemorySummary"](
            summary_type=row.get("summary_type", "user"),
            summary_text=row.get("summary_text", ""),
            key_facts=row.get("key_facts", []),
            facts_count=row.get("facts_count", 0),
            is_current=row.get("is_current", True),
        )
