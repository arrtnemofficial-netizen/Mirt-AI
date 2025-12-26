"""
Memory Service compatibility shim.

Keep existing imports stable while implementation lives in src/services/memory/.
"""

import warnings

from src.services.memory import MemoryService, create_memory_service
from src.services.memory.constants import (
    DEFAULT_FACTS_LIMIT,
    MAX_FACTS_LIMIT,
    MIN_IMPORTANCE_TO_STORE,
    MIN_SURPRISE_TO_STORE,
)

warnings.warn(
    "src.services.memory_service is deprecated; use src.services.memory.MemoryService",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "MemoryService",
    "create_memory_service",
    "MIN_IMPORTANCE_TO_STORE",
    "MIN_SURPRISE_TO_STORE",
    "DEFAULT_FACTS_LIMIT",
    "MAX_FACTS_LIMIT",
]
