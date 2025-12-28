"""Memory service constants."""


def _get_min_importance() -> float:
    """Get minimum importance threshold from settings."""
    try:
        from src.conf.config import settings
        return float(getattr(settings, "MEMORY_MIN_IMPORTANCE", 0.6))
    except Exception:
        return 0.6


def _get_min_surprise() -> float:
    """Get minimum surprise threshold from settings."""
    try:
        from src.conf.config import settings
        return float(getattr(settings, "MEMORY_MIN_SURPRISE", 0.4))
    except Exception:
        return 0.4


# Use configurable thresholds from settings (lazy loaded to avoid circular imports)
MIN_IMPORTANCE_TO_STORE = _get_min_importance()
MIN_SURPRISE_TO_STORE = _get_min_surprise()

DEFAULT_FACTS_LIMIT = 10
MAX_FACTS_LIMIT = 50

TABLE_PROFILES = "mirt_profiles"
TABLE_MEMORIES = "mirt_memories"
TABLE_SUMMARIES = "mirt_memory_summaries"
