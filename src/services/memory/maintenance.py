from __future__ import annotations

import logging
from datetime import UTC, datetime

from psycopg.rows import dict_row

from src.services.memory.base import MemoryBase
from src.services.memory.constants import TABLE_MEMORIES


logger = logging.getLogger(__name__)


class MaintenanceMixin(MemoryBase):
    """Maintenance tasks for memory tables."""

    async def apply_time_decay(self) -> int:
        if not self._enabled:
            return 0

        def _query():
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT apply_memory_decay() AS affected")
                    row = cur.fetchone()
                conn.commit()
            return row

        try:
            row = await self._run_db(_query)
            affected = int(row.get("affected", 0)) if row else 0
            logger.info("Applied time decay to %d memories", affected)
            return affected
        except Exception as e:
            logger.error("Failed to apply time decay: %s", e)
            return 0

    async def cleanup_expired(self) -> int:
        if not self._enabled:
            return 0

        def _query():
            now = datetime.now(UTC).isoformat()
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE {TABLE_MEMORIES}
                        SET is_active = FALSE
                        WHERE expires_at < %s
                          AND is_active = TRUE
                        """,
                        (now,),
                    )
                    count = cur.rowcount
                conn.commit()
            return count

        try:
            count = await self._run_db(_query)
            logger.info("Cleaned up %d expired memories", count)
            return count
        except Exception as e:
            logger.error("Failed to cleanup expired: %s", e)
            return 0
