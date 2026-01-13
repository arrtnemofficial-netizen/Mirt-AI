"""
Memory Models - DEPRECATED LOCATION.
=====================================

⚠️ This file is a BACKWARD COMPATIBILITY SHIM.
The canonical location is: src/services/memory/models.py

Import from there directly:
>>> from src.services.memory.models import Fact, UserProfile, MemoryContext
"""

import warnings

warnings.warn(
    "Importing from src.agents.pydantic.memory_models is deprecated. "
    "Use src.services.memory.models instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything from canonical location
from src.services.memory.models import (
    ChildProfile,
    CommerceInfo,
    DeleteFact,
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

__all__ = [
    "ChildProfile",
    "CommerceInfo",
    "DeleteFact",
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
