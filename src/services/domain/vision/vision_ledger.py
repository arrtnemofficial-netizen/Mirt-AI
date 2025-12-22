from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

try:
    from supabase import Client, create_client
except Exception:  # pragma: no cover - optional dependency
    Client = Any  # type: ignore[assignment]
    create_client = None

from src.conf.config import settings
from src.services.infra.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

LEDGER_STATUS_PROCESSING = "processing"
LEDGER_STATUS_PROCESSED = "processed"
LEDGER_STATUS_ESCALATED = "escalated"
LEDGER_STATUS_BLOCKED = "blocked"
LEDGER_STATUS_FAILED = "failed"

_IN_MEMORY_LEDGER: dict[str, dict[str, Any]] = {}


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def _sanitize_payload(data: Any) -> Any:
    if data is None:
        return None
    try:
        return json.loads(json.dumps(data, default=_json_default))
    except Exception:
        logger.debug("VisionLedger: failed to sanitize payload, dropping field", exc_info=True)
        return None


class VisionLedger:
    """Persistence helper for Vision results idempotency."""

    def __init__(self, supabase_client: Client | None = None):
        self.supabase = supabase_client or get_supabase_client()
        self._in_memory = self.supabase is None

    def get_by_hash(self, image_hash: str | None) -> dict[str, Any] | None:
        if not image_hash:
            return None
        if self._in_memory:
            record = _IN_MEMORY_LEDGER.get(image_hash)
            return dict(record) if record else None
        try:
            response = (
                self.supabase.table("vision_results")
                .select("*")
                .eq("image_hash", image_hash)
                .limit(1)
                .execute()
            )
            if response.data:
                return response.data[0]
        except Exception as exc:  # pragma: no cover - network dependency
            logger.warning("VisionLedger.get_by_hash failed: %s", exc)
        return None

    def record_result(
        self,
        *,
        session_id: str,
        image_hash: str | None,
        status: str,
        confidence: float | None = None,
        identified_product: Any | None = None,
        metadata: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any] | None:
        if not image_hash:
            return None

        payload = {
            "session_id": session_id,
            "image_hash": image_hash,
            "status": status,
            "confidence": confidence,
            "identified_product": _sanitize_payload(identified_product),
            "metadata": _sanitize_payload(metadata),
            "error_message": error_message,
            "updated_at": datetime.now(UTC).isoformat(),
        }

        if self._in_memory:
            now_iso = datetime.now(UTC).isoformat()
            existing = _IN_MEMORY_LEDGER.get(image_hash)
            if existing:
                existing.update({k: v for k, v in payload.items() if v is not None})
                existing["updated_at"] = now_iso
                record = existing
            else:
                record = {
                    "vision_result_id": str(uuid4()),
                    **payload,
                    "created_at": now_iso,
                }
            _IN_MEMORY_LEDGER[image_hash] = record
            return dict(record)

        try:
            response = (
                self.supabase.table("vision_results")
                .upsert(
                    payload,
                    on_conflict="image_hash",
                    returning="representation",
                )
                .execute()
            )
            if response.data:
                return response.data[0]
        except Exception as exc:  # pragma: no cover - network dependency
            logger.warning("VisionLedger.record_result failed: %s", exc)
        return None


@lru_cache(maxsize=1)
def get_vision_ledger() -> VisionLedger:
    client = get_supabase_client()
    if client is None and settings.SUPABASE_URL and settings.SUPABASE_API_KEY.get_secret_value() and create_client:
        try:
            client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_API_KEY.get_secret_value(),
            )
        except Exception:
            client = None
    return VisionLedger(client)


def reset_in_memory_vision_ledger() -> None:
    """Utility for tests to clear in-memory store."""
    _IN_MEMORY_LEDGER.clear()
