"""Database-backed idempotency for webhooks (no Redis required)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)


class WebhookDedupeStore:
    """Database-backed webhook deduplication with TTL cleanup.
    
    Supports both Supabase (legacy) and PostgreSQL.
    """

    def __init__(self, db: Client | None = None, ttl_hours: int = 24, use_postgres: bool = False):
        self.db = db  # Supabase client (legacy)
        self.use_postgres = use_postgres
        self.ttl_hours = ttl_hours

    def _hash_fallback(self, user_id: str, text: str, image_url: str | None) -> str:
        """Generate fallback hash for messages without message_id."""
        # Normalize text
        text = (text or "").strip().lower()
        image_url = (image_url or "").strip().lower()

        # Use 5-minute bucket for time-based deduplication
        bucket = int(time.time() // 300)  # 5 minutes

        data = f"{user_id}|{text}|{image_url}|{bucket}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def check_and_mark(
        self,
        *,
        user_id: str,
        message_id: str | None = None,
        text: str | None = None,
        image_url: str | None = None,
    ) -> bool:
        """Check if webhook was processed and mark as processed.

        Returns True if duplicate, False if first time.
        """
        if self.use_postgres:
            return asyncio.run(self._check_and_mark_postgres(user_id, message_id, text, image_url))
        else:
            return self._check_and_mark_supabase(user_id, message_id, text, image_url)

    def _check_and_mark_supabase(
        self,
        user_id: str,
        message_id: str | None,
        text: str | None,
        image_url: str | None,
    ) -> bool:
        """Supabase implementation."""
        if not self.db:
            logger.warning("Supabase client not available, skipping dedupe")
            return False

        if message_id:
            dedupe_key = f"manychat:{user_id}:{message_id}"
        else:
            hash_part = self._hash_fallback(user_id, text or "", image_url)
            dedupe_key = f"manychat:{user_id}:hash_{hash_part}"

        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=self.ttl_hours)

        try:
            (
                self.db.table("webhook_dedupe")
                .insert(
                    {
                        "dedupe_key": dedupe_key,
                        "processed_at": now.isoformat(),
                        "expires_at": expires_at.isoformat(),
                    }
                )
                .execute()
            )
            logger.debug("Webhook dedupe: marked %s", dedupe_key)
            return False
        except Exception as e:
            if "duplicate key" in str(e).lower() or "already exists" in str(e).lower():
                logger.info("Webhook dedupe: duplicate %s", dedupe_key)
                return True
            logger.error("Webhook dedupe error: %s", e)
            return False

    async def _check_and_mark_postgres(
        self,
        user_id: str,
        message_id: str | None,
        text: str | None,
        image_url: str | None,
    ) -> bool:
        """PostgreSQL implementation."""
        from src.services.postgres_pool import get_postgres_pool

        if message_id:
            dedupe_key = f"manychat:{user_id}:{message_id}"
        else:
            hash_part = self._hash_fallback(user_id, text or "", image_url)
            dedupe_key = f"manychat:{user_id}:hash_{hash_part}"

        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=self.ttl_hours)

        try:
            pool = await get_postgres_pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    try:
                        await cur.execute(
                            """
                            INSERT INTO webhook_dedupe (dedupe_key, processed_at, expires_at)
                            VALUES (%s, %s, %s)
                            """,
                            (dedupe_key, now, expires_at),
                        )
                        await conn.commit()
                        logger.debug("Webhook dedupe: marked %s", dedupe_key)
                        return False
                    except Exception as e:
                        await conn.rollback()
                        # Check if it's a duplicate (unique constraint violation)
                        if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                            logger.info("Webhook dedupe: duplicate %s", dedupe_key)
                            return True
                        raise
        except Exception as e:
            logger.error("Webhook dedupe error: %s", e)
            return False

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count of cleaned rows."""
        if self.use_postgres:
            return asyncio.run(self._cleanup_expired_postgres())
        else:
            return self._cleanup_expired_supabase()

    def _cleanup_expired_supabase(self) -> int:
        """Supabase implementation."""
        if not self.db:
            return 0

        cutoff = datetime.now(UTC).isoformat()

        try:
            result = self.db.table("webhook_dedupe").delete().lt("expires_at", cutoff).execute()
            count = len(result.data) if result.data else 0
            if count:
                logger.debug("Cleaned up %d expired webhook dedupe entries", count)
            return count
        except Exception as e:
            logger.error("Failed to cleanup webhook dedupe: %s", e)
            return 0

    async def _cleanup_expired_postgres(self) -> int:
        """PostgreSQL implementation."""
        from src.services.postgres_pool import get_postgres_pool

        try:
            pool = await get_postgres_pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "DELETE FROM webhook_dedupe WHERE expires_at < NOW()"
                    )
                    await conn.commit()
                    count = cur.rowcount
                    if count:
                        logger.debug("Cleaned up %d expired webhook dedupe entries", count)
                    return count
        except Exception as e:
            logger.error("Failed to cleanup webhook dedupe: %s", e)
            return 0
