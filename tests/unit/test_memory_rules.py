from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.services.memory.facts import FactsMixin
from src.services.memory.memory_rules import DEFAULT_MEMORY_RULES, FactRejectReason, resolve_ttl_days


class _FactsProbe(FactsMixin):
    def __init__(self):
        self._enabled = False


def test_ttl_defaults_by_fact_type() -> None:
    assert resolve_ttl_days("feedback", None) == 90
    assert resolve_ttl_days("logistics", None) == 180
    assert resolve_ttl_days("preference", 7) == 7


def test_context_rejection_reason_codes() -> None:
    probe = _FactsProbe()

    assert probe._get_rejection_reason_for_context({"is_active": False}) == FactRejectReason.INACTIVE
    assert (
        probe._get_rejection_reason_for_context(
            {"is_active": True, "expires_at": datetime.now(UTC) - timedelta(days=1)}
        )
        == FactRejectReason.EXPIRED
    )
    assert (
        probe._get_rejection_reason_for_context(
            {"is_active": True, "expires_at": None, "confidence": DEFAULT_MEMORY_RULES.min_confidence_to_use - 0.1}
        )
        == FactRejectReason.LOW_CONFIDENCE
    )
    assert (
        probe._get_rejection_reason_for_context(
            {"is_active": True, "expires_at": None, "confidence": DEFAULT_MEMORY_RULES.min_confidence_to_use, "content": ""}
        )
        == FactRejectReason.INVALID_FACT
    )
