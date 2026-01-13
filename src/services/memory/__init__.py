from __future__ import annotations

from src.services.memory.base import MemoryBase
from src.services.memory.context import ContextMixin
from src.services.memory.facts import FactsMixin
from src.services.memory.maintenance import MaintenanceMixin
from src.services.memory.profiles import ProfilesMixin
from src.services.memory.summaries import SummariesMixin

# Export models (SSOT)
from src.services.memory.models import (
    ChildProfile,
    CommerceInfo,
    Fact,
    FactCategory,
    FactType,
    LogisticsInfo,
    MemoryContext,
    MemoryDecision,
    MemorySummary,
    NewFact,
    StylePreferences,
    UpdateFact,
    UserProfile,
)


class MemoryService(
    ProfilesMixin,
    FactsMixin,
    SummariesMixin,
    ContextMixin,
    MaintenanceMixin,
    MemoryBase,
):
    """Facade that aggregates memory operations."""

    def __init__(self, client=None) -> None:
        super().__init__(client=client)


def create_memory_service() -> MemoryService:
    """Factory function for MemoryService."""
    return MemoryService()


__all__ = [
    # Service
    "MemoryService",
    "create_memory_service",
    # Models (SSOT)
    "ChildProfile",
    "CommerceInfo",
    "Fact",
    "FactCategory",
    "FactType",
    "LogisticsInfo",
    "MemoryContext",
    "MemoryDecision",
    "MemorySummary",
    "NewFact",
    "StylePreferences",
    "UpdateFact",
    "UserProfile",
]
