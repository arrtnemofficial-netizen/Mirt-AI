from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from src.services.memory.constants import MIN_IMPORTANCE_TO_STORE
from src.services.memory.models import FactType


class FactRejectReason(StrEnum):
    LOW_IMPORTANCE = "LOW_IMPORTANCE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    EXPIRED = "EXPIRED"
    INACTIVE = "INACTIVE"
    INVALID_FACT = "INVALID_FACT"


@dataclass(frozen=True)
class MemoryRules:
    min_importance_to_store: float = MIN_IMPORTANCE_TO_STORE
    min_confidence_to_use: float = 0.55
    ttl_days_by_fact_type: dict[str, int | None] = field(
        default_factory=lambda: {
            "preference": 365,
            "constraint": 365,
            "logistics": 180,
            "behavior": 180,
            "feedback": 90,
            "child_info": 365,
        }
    )


DEFAULT_MEMORY_RULES = MemoryRules()


def resolve_ttl_days(
    fact_type: FactType,
    ttl_days: int | None,
    rules: MemoryRules = DEFAULT_MEMORY_RULES,
) -> int | None:
    if ttl_days is not None:
        return ttl_days
    return rules.ttl_days_by_fact_type.get(fact_type)


def is_fact_expired(expires_at: datetime | str | None, now: datetime | None = None) -> bool:
    if expires_at is None:
        return False
    current = now or datetime.now(UTC)
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= current
