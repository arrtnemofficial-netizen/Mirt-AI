"""Database-backed idempotency for webhooks (no Redis required)."""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client


logger = logging.getLogger(__name__)


class WebhookDedupeStore:
    """Supabase-backed webhook deduplication with TTL cleanup."""

    def __init__(self, db: Client, ttl_hours: int = 24):
        self.db = db
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
        if message_id:
            dedupe_key = f"manychat:{user_id}:{message_id}"
        else:
            # Fallback to hash-based key
            hash_part = self._hash_fallback(user_id, text or "", image_url)
            dedupe_key = f"manychat:{user_id}:hash_{hash_part}"
        
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=self.ttl_hours)
        
        try:
            # Try to insert - if exists, will raise error
            result = (
                self.db.table("webhook_dedupe")
                .insert({
                    "dedupe_key": dedupe_key,
                    "processed_at": now.isoformat(),
                    "expires_at": expires_at.isoformat(),
                })
                .execute()
            )
            
            # Successfully inserted = not duplicate
            logger.debug("Webhook dedupe: marked %s", dedupe_key)
            return False
            
        except Exception as e:
            # Check if it's a duplicate (unique constraint violation)
            if "duplicate key" in str(e).lower() or "already exists" in str(e).lower():
                logger.info("Webhook dedupe: duplicate %s", dedupe_key)
                return True
            
            # Other error - log but allow processing
            logger.error("Webhook dedupe error: %s", e)
            return False

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count of cleaned rows."""
        cutoff = datetime.now(timezone.utc).isoformat()
        
        try:
            result = (
                self.db.table("webhook_dedupe")
                .delete()
                .lt("expires_at", cutoff)
                .execute()
            )
            
            count = len(result.data) if result.data else 0
            if count:
                logger.debug("Cleaned up %d expired webhook dedupe entries", count)
            return count
            
        except Exception as e:
            logger.error("Failed to cleanup webhook dedupe: %s", e)
            return 0
