"""
Production Checkpointer - State Persistence.
=============================================
This is THE critical component for production.

Without this:
- Server restart = lost conversations
- Deploy = angry customers
- Scale = chaos

With this:
- Server dies? Who cares, state is in Postgres
- 10 servers? All share the same state
- Customer returns after a week? Continue exactly where they left off
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver


if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)


class SerializableMemorySaver(MemorySaver):
    """MemorySaver wrapper that handles LangChain Message serialization.

    This is a fallback for when DATABASE_URL is not available.
    Converts Message objects to dicts for JSON serialization compatibility.
    """

    def _serialize_value(self, value: Any) -> Any:
        """Recursively serialize values, converting Message objects to dicts."""
        if isinstance(value, BaseMessage):
            # Convert LangChain Message to dict format
            return {
                "type": value.type,
                "content": value.content,
                "additional_kwargs": getattr(value, "additional_kwargs", {}),
                "response_metadata": getattr(value, "response_metadata", {}),
            }
        elif isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._serialize_value(item) for item in value]
        else:
            return value

    def put(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: dict[str, str],
    ) -> dict[str, Any]:
        """Override put to serialize Message objects before storage."""
        try:
            # Serialize checkpoint data to handle Message objects
            serialized_checkpoint = self._serialize_value(checkpoint)
            serialized_metadata = self._serialize_value(metadata)
            return super().put(config, serialized_checkpoint, serialized_metadata, new_versions)
        except Exception as e:
            logger.error(f"SerializableMemorySaver put failed: {e}")
            # Fallback to original method
            return super().put(config, checkpoint, metadata, new_versions)


class CheckpointerType(str, Enum):
    """Available checkpointer backends."""

    MEMORY = "memory"  # Development only! State lost on restart
    POSTGRES = "postgres"  # Production - use this
    REDIS = "redis"  # Alternative for high-throughput


# =============================================================================
# SINGLETON INSTANCES
# =============================================================================

_checkpointer: BaseCheckpointSaver | None = None
_checkpointer_type: CheckpointerType | None = None


# =============================================================================
# POSTGRES CHECKPOINTER (Production)
# =============================================================================


def get_postgres_checkpointer() -> BaseCheckpointSaver:
    """
    Create PostgreSQL checkpointer for production.

    Requires:
    - DATABASE_URL or POSTGRES_URL environment variable
    - langgraph-checkpoint-postgres package

    The checkpointer will:
    - Create tables automatically on first use
    - Store full state at every step
    - Enable time travel and forking
    """
    settings = None
    # Try to get database URL from environment
    database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")

    if not database_url:
        try:
            from src.conf.config import settings as app_settings

            settings = app_settings
            if getattr(settings, "DATABASE_URL", ""):
                database_url = settings.DATABASE_URL
        except Exception:
            logger.debug("Unable to load settings for DATABASE_URL fallback", exc_info=True)

    if not database_url:
        # Try to build from Supabase settings
        if settings is None:
            from src.conf.config import settings as app_settings

            settings = app_settings

        if hasattr(settings, "SUPABASE_URL") and hasattr(settings, "SUPABASE_API_KEY"):
            # Supabase connection string format
            supabase_url = str(settings.SUPABASE_URL)
            logger.info(f"DEBUG: Supabase URL found: {supabase_url[:20]}...")
            logger.info(
                f"DEBUG: Supabase API key present: {bool(settings.SUPABASE_API_KEY.get_secret_value())}"
            )

            if "supabase" in supabase_url:
                # Extract project ref from URL
                # https://xxx.supabase.co -> xxx
                import re

                match = re.search(r"https://([^.]+)\.supabase", supabase_url)
                logger.info(f"DEBUG: Regex match result: {match}")

                if match:
                    project_ref = match.group(1)
                    logger.info(f"DEBUG: Extracted project_ref: {project_ref}")
                    # Build postgres connection string
                    # Default Supabase postgres port is 5432, password from service_role key
                    database_url = f"postgresql://postgres:{settings.SUPABASE_API_KEY.get_secret_value()}@db.{project_ref}.supabase.co:5432/postgres"
                    logger.info(
                        f"DEBUG: Built DATABASE_URL: postgresql://postgres:***@db.{project_ref}.supabase.co:5432/postgres"
                    )

    if not database_url:
        logger.warning(
            "No DATABASE_URL found. Falling back to MemorySaver. "
            "THIS IS NOT PRODUCTION-READY! Set DATABASE_URL for persistence."
        )
        return SerializableMemorySaver()

    try:
        # Create async connection pool for async checkpointing
        import psycopg
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        # First, setup tables with a separate autocommit connection (sync is fine for setup)
        setup_conn = psycopg.connect(database_url, autocommit=True)
        try:
            # Use sync PostgresSaver just for table setup
            from langgraph.checkpoint.postgres import PostgresSaver as SyncPostgresSaver

            setup_checkpointer = SyncPostgresSaver(setup_conn)
            setup_checkpointer.setup()
        finally:
            setup_conn.close()

        # Now create ASYNC pool for actual checkpointing (required for ainvoke)
        pool = AsyncConnectionPool(conninfo=database_url, min_size=1, max_size=5)
        checkpointer = AsyncPostgresSaver(pool)

        logger.info("AsyncPostgresSaver checkpointer initialized successfully")
        return checkpointer

    except ImportError as e:
        logger.error(
            "langgraph-checkpoint-postgres not installed or import error: %s. "
            "Run: pip install langgraph-checkpoint-postgres",
            e,
        )
        return SerializableMemorySaver()

    except Exception as e:
        logger.error("Failed to create PostgreSQL checkpointer: %s", e)
        logger.warning("Falling back to MemorySaver - NOT PRODUCTION READY!")
        return SerializableMemorySaver()


# =============================================================================
# REDIS CHECKPOINTER (Alternative)
# =============================================================================


def get_redis_checkpointer() -> BaseCheckpointSaver:
    """
    Create Redis checkpointer for high-throughput scenarios.

    Requires:
    - REDIS_URL environment variable
    - langgraph-checkpoint-redis package
    """
    redis_url = os.getenv("REDIS_URL")

    if not redis_url:
        from src.conf.config import settings

        redis_url = getattr(settings, "REDIS_URL", None)

    if not redis_url:
        logger.warning("No REDIS_URL found. Falling back to MemorySaver.")
        return SerializableMemorySaver()

    try:
        # Redis checkpointer might not be available yet in langgraph
        # Fall back to Postgres or Memory
        logger.info("Redis checkpointer requested, but using Postgres as fallback")
        return get_postgres_checkpointer()

    except Exception as e:
        logger.error("Failed to create Redis checkpointer: %s", e)
        return SerializableMemorySaver()


# =============================================================================
# MAIN FACTORY
# =============================================================================


def get_checkpointer(
    checkpointer_type: CheckpointerType | None = None,
    force_new: bool = False,
) -> BaseCheckpointSaver:
    """
    Get or create the appropriate checkpointer.

    Args:
        checkpointer_type: Which backend to use (auto-detect if None)
        force_new: Create new instance even if one exists

    Returns:
        Configured checkpointer instance

    Auto-detection priority:
    1. DATABASE_URL present -> PostgresSaver
    2. REDIS_URL present -> (future) RedisSaver
    3. Nothing -> MemorySaver (with warning)
    """
    global _checkpointer, _checkpointer_type

    # Return cached if available and not forcing new
    if _checkpointer is not None and not force_new:
        return _checkpointer

    # Auto-detect type if not specified
    # Import settings for proper .env loading via pydantic_settings
    from src.conf.config import settings as app_settings

    if checkpointer_type is None:
        # Only auto-select POSTGRES when an explicit database URL is provided.
        # The presence of SUPABASE_URL alone is not enough in development, otherwise
        # local runs (like Telegram polling) will break when Postgres is not ready.
        if app_settings.DATABASE_URL or os.getenv("POSTGRES_URL"):
            checkpointer_type = CheckpointerType.POSTGRES
        elif os.getenv("REDIS_URL"):
            checkpointer_type = CheckpointerType.REDIS
        else:
            # Check if we're in production
            env = os.getenv("ENVIRONMENT", "development").lower()
            if env in ("production", "prod", "staging"):
                logger.error(
                    "Running in %s without DATABASE_URL! "
                    "State will be lost on restart. "
                    "This is a CRITICAL configuration error.",
                    env,
                )
            checkpointer_type = CheckpointerType.MEMORY

    # Create checkpointer
    if checkpointer_type == CheckpointerType.POSTGRES:
        _checkpointer = get_postgres_checkpointer()
    elif checkpointer_type == CheckpointerType.REDIS:
        _checkpointer = get_redis_checkpointer()
    else:
        logger.warning(
            "Using MemorySaver - state will be lost on restart! "
            "Set DATABASE_URL for production persistence."
        )
        _checkpointer = SerializableMemorySaver()

    logger.info("Checkpointer selected: %s", checkpointer_type)

    _checkpointer_type = checkpointer_type
    return _checkpointer


def get_current_checkpointer_type() -> CheckpointerType | None:
    """Get the type of the current checkpointer."""
    return _checkpointer_type


def is_persistent() -> bool:
    """Check if the current checkpointer is persistent (survives restarts)."""
    return _checkpointer_type in (CheckpointerType.POSTGRES, CheckpointerType.REDIS)
