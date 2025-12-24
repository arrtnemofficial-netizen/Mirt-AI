from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
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
_LEDGER_SINGLETON: "VisionLedger | None" = None
_PYTEST_LEDGER: "VisionLedger | None" = None
_PYTEST_TEST_ID: str | None = None


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

    def __init__(self, supabase_client: Client | None = None, *, auto_client: bool = True):
        # IMPORTANT: allow callers (tests) to force in-memory mode.
        # Using `supabase_client or get_supabase_client()` would defeat that.
        if auto_client and supabase_client is None:
            supabase_client = get_supabase_client()
        self.supabase = supabase_client
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


def get_vision_ledger() -> VisionLedger:
    # Test isolation:
    # Unit tests patch/expect `vision_node` to call the vision agent.
    # If we use a real Supabase-backed ledger (or a cached in-memory ledger),
    # a previous test can mark the same (session_id,image_url) hash as final and
    # `vision_node` will early-return as "duplicate" without calling run_vision.
    #
    # Under pytest we force an in-memory ledger and reset it for determinism.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        # Test isolation, but stable within a single test:
        # - We want duplicate detection to work within one test function
        # - We must avoid cross-test pollution (same hash reused in other tests)
        global _PYTEST_LEDGER, _PYTEST_TEST_ID
        test_id = (os.environ.get("PYTEST_CURRENT_TEST") or "").split(" ")[0]
        if test_id and test_id != _PYTEST_TEST_ID:
            reset_in_memory_vision_ledger()
            _PYTEST_TEST_ID = test_id
            _PYTEST_LEDGER = VisionLedger(None, auto_client=False)
        if _PYTEST_LEDGER is None:
            _PYTEST_LEDGER = VisionLedger(None, auto_client=False)
        return _PYTEST_LEDGER

    global _LEDGER_SINGLETON
    if _LEDGER_SINGLETON is not None:
        return _LEDGER_SINGLETON

    client = get_supabase_client()
    if client is None and settings.SUPABASE_URL and settings.SUPABASE_API_KEY.get_secret_value() and create_client:
        try:
            client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_API_KEY.get_secret_value(),
            )
        except Exception:
            client = None
    _LEDGER_SINGLETON = VisionLedger(client)
    return _LEDGER_SINGLETON


def _cache_clear() -> None:
    """Backward-compatible cache_clear API (some tests call get_vision_ledger.cache_clear())."""
    global _LEDGER_SINGLETON
    _LEDGER_SINGLETON = None
    global _PYTEST_LEDGER, _PYTEST_TEST_ID
    _PYTEST_LEDGER = None
    # IMPORTANT: do NOT reset _PYTEST_TEST_ID here.
    # Some tests call cache_clear() to refresh the ledger instance but still expect
    # the in-memory records to remain for duplicate detection within the same test.


# Expose cache_clear attribute for tests/backward compatibility.
get_vision_ledger.cache_clear = _cache_clear  # type: ignore[attr-defined]


def reset_in_memory_vision_ledger() -> None:
    """Utility for tests to clear in-memory store."""
    _IN_MEMORY_LEDGER.clear()
