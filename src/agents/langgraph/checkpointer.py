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
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver


if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

import time
from typing import Any

logger = logging.getLogger(__name__)


def _compact_payload(
    checkpoint: dict[str, Any],
    max_messages: int = 200,
    max_chars: int = 4000,
    drop_base64: bool = True,
) -> dict[str, Any]:
    """
    Compact checkpoint payload to keep database size manageable.
    - Limits total number of messages in state
    - Truncates very long messages
    - Optionally removes base64 image data
    
    SAFEGUARDS:
    - Whitelist critical fields (selected_products, customer_*)
    - Logging size before/after compaction
    - Optional disable via COMPACTION_ENABLED env var
    """
    from src.conf.config import get_settings

    settings = get_settings()
    
    # SAFEGUARD_4: Optional disable for debugging
    if not settings.COMPACTION_ENABLED:
        logger.debug("[COMPACTION] Disabled via COMPACTION_ENABLED=false")
        return checkpoint

    if not isinstance(checkpoint, dict) or "channel_values" not in checkpoint:
        return checkpoint

    cv = checkpoint["channel_values"]
    
    # SAFEGUARD_1: Whitelist critical fields - preserve them
    CRITICAL_FIELDS = {
        "selected_products",
        "customer_name",
        "customer_phone",
        "customer_city",
        "customer_nova_poshta",
    }
    
    # Store critical fields before compaction
    critical_data = {}
    for field in CRITICAL_FIELDS:
        if field in cv:
            critical_data[field] = cv[field]
    
    # SAFEGUARD_2: Log size before compaction
    import json
    payload_before = json.dumps(checkpoint, default=str)
    payload_size_before = len(payload_before)
    messages_before = len(cv.get("messages", [])) if "messages" in cv else 0
    
    if "messages" not in cv or not isinstance(cv["messages"], list):
        return checkpoint

    messages = cv["messages"]
    
    # 1. Limit message count (keep tail)
    if len(messages) > max_messages:
        messages = messages[-max_messages:]
    
    compacted = []
    for msg in messages:
        # For LangChain messages or dicts
        content = getattr(msg, "content", None)
        is_obj = True
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
            is_obj = False
        
        if isinstance(content, str):
            # 2. Drop base64
            if drop_base64 and ("base64" in content or "data:image" in content):
                content = "[IMAGE DATA REMOVED]"
            
            # 3. Truncate chars
            if len(content) > max_chars:
                content = content[:max_chars] + "... [TRUNCATED]"
            
            if is_obj:
                msg.content = content
            else:
                msg["content"] = content
        
        compacted.append(msg)
    
    cv["messages"] = compacted
    
    # SAFEGUARD_1: Restore critical fields (they should never be compacted)
    for field, value in critical_data.items():
        cv[field] = value
    
    # SAFEGUARD_2: Log size after compaction
    payload_after = json.dumps(checkpoint, default=str)
    payload_size_after = len(payload_after)
    messages_after = len(cv.get("messages", []))
    
    compaction_ratio = payload_size_after / payload_size_before if payload_size_before > 0 else 1.0
    
    logger.info(
        "[COMPACTION] Payload compacted: size_before=%d size_after=%d ratio=%.2f messages_before=%d messages_after=%d",
        payload_size_before,
        payload_size_after,
        compaction_ratio,
        messages_before,
        messages_after,
    )
    
    return checkpoint


def _log_if_slow(
    op: str,
    t0: float,
    config: Any,
    payload: Any = None,
    slow_threshold_s: float = 1.0,
) -> None:
    dt = time.perf_counter() - t0
    if dt > slow_threshold_s:
        session_id = (
            config.get("configurable", {}).get("thread_id", "unknown")
            if isinstance(config, dict)
            else "unknown"
        )
        logger.warning(
            f"SLOW CHECKPOINTER OP: {op} took {dt:.2f}s for session {session_id}"
        )


async def _open_pool_on_demand(pool: Any) -> None:
    """Ensure AsyncConnectionPool is open before use."""
    if pool is None:
        return
    if hasattr(pool, "open") and not getattr(pool, "_opened", False):
        open_result = pool.open()
        # pool.open() may return a coroutine or None
        if open_result is not None:
            await open_result


def _setting_int(settings: Any, key: str, default: int) -> int:
    return int(getattr(settings, key, default))


def _setting_float(settings: Any, key: str, default: float) -> float:
    return float(getattr(settings, key, default))


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

    def put(self, config: dict[str, Any], checkpoint: dict[str, Any], metadata: dict[str, Any], new_versions: dict[str, str]) -> dict[str, Any]:
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
    MEMORY = "memory"      # Development only! State lost on restart
    POSTGRES = "postgres"  # Production - use this
    REDIS = "redis"        # Alternative for high-throughput


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
    # Try to get database URL from environment
    database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")

    # Import settings at function start to ensure it's always available
    from src.conf.config import settings
    
    if not database_url:
        # Try to build from Supabase settings
        if hasattr(settings, "SUPABASE_URL") and hasattr(settings, "SUPABASE_API_KEY"):
            # Supabase connection string format
            supabase_url = str(settings.SUPABASE_URL)
            logger.info(f"DEBUG: Supabase URL found: {supabase_url[:20]}...")
            logger.info(f"DEBUG: Supabase API key present: {bool(settings.SUPABASE_API_KEY.get_secret_value())}")

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
                    logger.info(f"DEBUG: Built DATABASE_URL: postgresql://postgres:***@db.{project_ref}.supabase.co:5432/postgres")

    if not database_url:
        logger.warning(
            "No DATABASE_URL found. Falling back to MemorySaver. "
            "THIS IS NOT PRODUCTION-READY! Set DATABASE_URL for persistence."
        )
        return SerializableMemorySaver()

    try:
        # Import PostgresSaver and psycopg for connection management
        from langgraph.checkpoint.postgres import PostgresSaver
        import psycopg

        # First, setup tables with a separate autocommit connection
        # CREATE INDEX CONCURRENTLY requires autocommit mode
        setup_conn = psycopg.connect(database_url, autocommit=True)
        try:
            setup_checkpointer = PostgresSaver(setup_conn)
            setup_checkpointer.setup()
        finally:
            setup_conn.close()

        slow_threshold_s = _setting_float(settings, "CHECKPOINTER_SLOW_LOG_SECONDS", 1.0)

        from src.services.core.trim_policy import get_checkpoint_compaction

        max_messages, max_chars, drop_base64 = get_checkpoint_compaction(settings)

        # Create a connection for PostgresSaver initialization
        # PostgresSaver.__init__ expects a connection object (conn: '_internal.Conn'), not a pool
        # The connection is stored by PostgresSaver and used for database operations
        init_conn = psycopg.connect(database_url, autocommit=False)
        
        class InstrumentedAsyncPostgresSaver(PostgresSaver):
            """PostgresSaver with instrumentation and compaction."""
            
            # PostgresSaver uses the connection passed to __init__ for database operations
            # We don't need _ensure_pool_open since PostgresSaver manages the connection
            async def _ensure_pool_open(self) -> None:
                # PostgresSaver uses the connection passed during initialization
                # This method is kept for compatibility but is a no-op
                pass

            async def aget_tuple(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    # PostgresSaver handles connection internally via the conn passed to __init__
                    result = await super().aget_tuple(*args, **kwargs)
                    return result
                finally:
                    config = args[0] if args else None
                    payload = None
                    try:
                        if (
                            isinstance(locals().get("result"), tuple)
                            and len(locals()["result"]) > 0
                        ):
                            payload = locals()["result"][0]
                        else:
                            payload = locals().get("result")
                    except Exception:
                        payload = None
                    _log_if_slow(
                        "aget_tuple",
                        _t0,
                        config,
                        payload=payload,
                        slow_threshold_s=slow_threshold_s,
                    )

            async def aput(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    if len(args) > 1:
                        payload = _compact_payload(
                            args[1],
                            max_messages=max_messages,
                            max_chars=max_chars,
                            drop_base64=drop_base64,
                        )
                        args = (args[0], payload, *args[2:])
                    return await super().aput(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    payload = args[1] if len(args) > 1 else None
                    _log_if_slow(
                        "aput", _t0, config, payload=payload, slow_threshold_s=slow_threshold_s
                    )

            async def aput_writes(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    if len(args) > 1:
                        payload = _compact_payload(
                            args[1],
                            max_messages=max_messages,
                            max_chars=max_chars,
                            drop_base64=drop_base64,
                        )
                        args = (args[0], payload, *args[2:])
                    return await super().aput_writes(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    payload = args[1] if len(args) > 1 else None
                    _log_if_slow(
                        "aput_writes",
                        _t0,
                        config,
                        payload=payload,
                        slow_threshold_s=slow_threshold_s,
                    )

            def get_tuple(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    return super().get_tuple(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    _log_if_slow(
                        "get_tuple", _t0, config, payload=None, slow_threshold_s=slow_threshold_s
                    )

            def put(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    return super().put(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    _log_if_slow(
                        "put", _t0, config, payload=None, slow_threshold_s=slow_threshold_s
                    )

            def put_writes(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    return super().put_writes(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    _log_if_slow(
                        "put_writes", _t0, config, payload=None, slow_threshold_s=slow_threshold_s
                    )

        # PostgresSaver.__init__ expects a connection object (conn: '_internal.Conn')
        # PostgresSaver stores and uses this connection for database operations
        # The connection must remain open for PostgresSaver to function
        checkpointer = InstrumentedAsyncPostgresSaver(init_conn)
        
        # Note: init_conn is stored by PostgresSaver and should not be closed manually
        # PostgresSaver will manage the connection lifecycle

        logger.info("PostgresSaver checkpointer initialized successfully")
        return checkpointer

    except ImportError as import_err:
        logger.warning(
            "langgraph-checkpoint-postgres not available (fallback to MemorySaver). "
            "For production persistence, install: pip install langgraph-checkpoint-postgres. "
            f"Import error: {import_err}"
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
    if checkpointer_type is None:
        if os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL"):
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

    _checkpointer_type = checkpointer_type
    return _checkpointer


def get_current_checkpointer_type() -> CheckpointerType | None:
    """Get the type of the current checkpointer."""
    return _checkpointer_type


def is_persistent() -> bool:
    """Check if the current checkpointer is persistent (survives restarts)."""
    return _checkpointer_type in (CheckpointerType.POSTGRES, CheckpointerType.REDIS)


async def warmup_checkpointer_pool() -> bool:
    """
    Warm up the checkpointer connection to avoid first-request delay.
    
    Returns:
        True if warmup succeeded, False otherwise (non-blocking)
    """
    global _checkpointer_type
    
    try:
        # Ensure checkpointer is initialized
        get_checkpointer()
        
        # PostgresSaver manages its own connection internally
        # No explicit warmup needed - connection is created during initialization
        if _checkpointer_type == CheckpointerType.POSTGRES:
            logger.info("PostgresSaver checkpointer initialized (connection managed internally)")
            return True
        
        # For MemorySaver or other non-pool checkpointers, warmup is not needed
        logger.debug("Checkpointer warmup not needed (using %s)", _checkpointer_type)
        return True
        
    except Exception as e:
        logger.warning("Checkpointer warmup failed: %s", e)
        return False