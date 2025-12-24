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

    def _strip_base64(obj: Any) -> Any:
        """Recursively replace base64/data URLs with a stable placeholder."""
        if isinstance(obj, str):
            if drop_base64 and ("data:image" in obj or "base64" in obj):
                return "<base64_stripped>"
            return obj
        if isinstance(obj, dict):
            return {k: _strip_base64(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_strip_base64(v) for v in obj]
        return obj
    
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
                content = "<base64_stripped>"
            
            # 3. Truncate chars
            if len(content) > max_chars:
                content = content[:max_chars] + "... [TRUNCATED]"
            
            if is_obj:
                msg.content = content
            else:
                msg["content"] = content
        
        compacted.append(msg)
    
    cv["messages"] = compacted

    # 4. Strip base64/data URLs from the rest of channel_values (e.g. image_url)
    # This keeps checkpoints small and makes tests deterministic.
    cv = _strip_base64(cv)
    checkpoint["channel_values"] = cv
    
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
_pool_instance: Any = None  # Store pool reference for graceful shutdown


# =============================================================================
# POSTGRES CHECKPOINTER (Production)
# =============================================================================


def get_postgres_checkpointer() -> BaseCheckpointSaver:
    """
    Create PostgreSQL checkpointer for production.

    Requires (in priority order):
    - DATABASE_URL_POOLER (recommended for production with PgBouncer)
    - DATABASE_URL or POSTGRES_URL environment variable
    - Auto-build from SUPABASE_API_KEY (development only, disabled in production/staging)
    - langgraph-checkpoint-postgres package

    Environment detection:
    - Production/staging: Requires explicit DATABASE_URL or DATABASE_URL_POOLER
    - Development: Allows auto-build from SUPABASE_API_KEY as fallback

    The checkpointer will:
    - Create tables automatically on first use
    - Store full state at every step
    - Enable time travel and forking
    - Use prepare_threshold=None to disable prepared statements (PgBouncer compatible)
    - Open pool on-demand (lazy initialization)
    """
    # Try to get database URL from environment
    # Priority: DATABASE_URL_POOLER > DATABASE_URL > POSTGRES_URL
    database_url = (
        os.getenv("DATABASE_URL_POOLER") 
        or os.getenv("DATABASE_URL") 
        or os.getenv("POSTGRES_URL")
    )

    # Import settings at function start to ensure it's always available
    from src.conf.config import settings
    
    # Determine environment
    env = os.getenv("ENVIRONMENT", "development").lower()
    is_production = env in ("production", "prod", "staging")
    
    if not database_url:
        if is_production:
            # In production/staging, require explicit DATABASE_URL
            logger.error(
                "CRITICAL: DATABASE_URL or DATABASE_URL_POOLER is required in %s environment! "
                "Auto-building from SUPABASE_API_KEY is disabled for production safety. "
                "Set DATABASE_URL or DATABASE_URL_POOLER explicitly.",
                env
            )
            raise ValueError(
                f"DATABASE_URL or DATABASE_URL_POOLER must be set explicitly in {env} environment. "
                "Auto-build from SUPABASE_API_KEY is disabled for production safety."
            )
        
        # Only allow auto-build in development/local environments
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
                    # NOTE: This uses direct connection, not pooler (for dev only)
                    database_url = f"postgresql://postgres:{settings.SUPABASE_API_KEY.get_secret_value()}@db.{project_ref}.supabase.co:5432/postgres"
                    logger.warning(
                        "Auto-built DATABASE_URL from SUPABASE_API_KEY (dev mode only). "
                        "For production, set DATABASE_URL_POOLER explicitly (recommended) or DATABASE_URL."
                    )

    if not database_url:
        logger.warning(
            "No DATABASE_URL found. Falling back to MemorySaver. "
            "THIS IS NOT PRODUCTION-READY! Set DATABASE_URL for persistence."
        )
        return SerializableMemorySaver()

    try:
        # Import async PostgresSaver and psycopg for connection management
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.checkpoint.postgres import PostgresSaver  # For sync setup only
        from psycopg_pool import AsyncConnectionPool
        import psycopg

        # Setup tables first using sync connection with prepare_threshold=None
        # None completely disables prepared statements (vs 0 which means "after 0 uses")
        setup_conn = psycopg.connect(database_url, autocommit=True, prepare_threshold=None)
        try:
            temp_checkpointer = PostgresSaver(setup_conn)
            temp_checkpointer.setup()
        finally:
            setup_conn.close()

        slow_threshold_s = _setting_float(settings, "CHECKPOINTER_SLOW_LOG_SECONDS", 1.0)

        from src.services.core.trim_policy import get_checkpoint_compaction

        max_messages, max_chars, drop_base64 = get_checkpoint_compaction(settings)

        # Create async pool with prepare_threshold=None
        # CRITICAL for Supabase PgBouncer which doesn't support prepared statements
        # None = never use prepared statements (0 still creates them after 0 uses)
        #
        # Also configure for Supabase connection limits:
        # - max_idle=30: Close idle connections before Supabase does (avoids SSL errors)
        # - check: Verify connection is alive before use

        async def check_connection(conn):
            """Check if connection is still alive before returning from pool.
            
            Optimized: Lightweight health check. Connection pool tracks last_used internally.
            """
            try:
                # Use a lightweight query - PostgreSQL optimizes SELECT 1
                await conn.execute("SELECT 1")
            except Exception:
                raise  # Connection is dead, pool will discard it

        # Optimized pool settings for better performance
        # Increased min_size to reduce connection acquisition time (warm pool)
        pool_min_size = _setting_int(settings, "CHECKPOINTER_POOL_MIN_SIZE", 2)  # Was 1, now 2 for faster access
        pool_max_size = _setting_int(settings, "CHECKPOINTER_POOL_MAX_SIZE", 5)
        pool_timeout_s = _setting_float(settings, "CHECKPOINTER_POOL_TIMEOUT_SECONDS", 15.0)
        pool_max_idle_s = _setting_float(settings, "CHECKPOINTER_POOL_MAX_IDLE_SECONDS", 120.0)
        # Reduced connect_timeout for faster failure detection
        connect_timeout_s = _setting_float(settings, "CHECKPOINTER_CONNECT_TIMEOUT_SECONDS", 5.0)  # Was 10.0, now 5.0

        statement_timeout_ms = _setting_int(settings, "CHECKPOINTER_STATEMENT_TIMEOUT_MS", 8000)
        lock_timeout_ms = _setting_int(settings, "CHECKPOINTER_LOCK_TIMEOUT_MS", 2000)

        pool_min_size = max(pool_min_size, 0)
        pool_max_size = max(pool_max_size, 1)
        pool_min_size = min(pool_min_size, pool_max_size)

        options = None
        if statement_timeout_ms > 0 or lock_timeout_ms > 0:
            parts: list[str] = []
            if statement_timeout_ms > 0:
                parts.append(f"-c statement_timeout={statement_timeout_ms}")
            if lock_timeout_ms > 0:
                parts.append(f"-c lock_timeout={lock_timeout_ms}")
            options = " ".join(parts) if parts else None

        pool_kwargs: dict[str, Any] = {
            "prepare_threshold": None,  # CRITICAL: Completely disable prepared statements
            "connect_timeout": connect_timeout_s,
        }
        if options:
            pool_kwargs["options"] = options

        try:
            pool = AsyncConnectionPool(
                conninfo=database_url,
                min_size=pool_min_size,
                max_size=pool_max_size,
                max_idle=pool_max_idle_s,
                check=check_connection,  # Verify connection health before use
                timeout=pool_timeout_s,
                open=False,
                kwargs=pool_kwargs,
            )
        except TypeError:
            pool = AsyncConnectionPool(
                conninfo=database_url,
                min_size=pool_min_size,
                max_size=pool_max_size,
                max_idle=pool_max_idle_s,
                check=check_connection,  # Verify connection health before use
                timeout=pool_timeout_s,
                kwargs=pool_kwargs,
            )
        
        # Store pool reference for graceful shutdown
        global _pool_instance
        _pool_instance = pool
        
        # Create AsyncPostgresSaver instance using async pool
        base_checkpointer = AsyncPostgresSaver(conn=pool)
        
        # Use composition instead of inheritance to avoid super() NotImplementedError issues
        # Wrap AsyncPostgresSaver and delegate all method calls to it
        class InstrumentedAsyncPostgresSaver:
            """Wrapper around AsyncPostgresSaver with instrumentation and compaction."""
            
            def __init__(self, base: AsyncPostgresSaver, pool: AsyncConnectionPool):
                self._base = base
                self._pool = pool  # Store pool reference for lifecycle management
            
            async def _ensure_pool_open(self) -> None:
                """Ensure pool is open before use (on-demand opening)."""
                await _open_pool_on_demand(self._pool)
            
            async def aget_tuple(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                result = None
                try:
                    await self._ensure_pool_open()
                    # Delegate directly to base AsyncPostgresSaver instance
                    result = await self._base.aget_tuple(*args, **kwargs)
                    return result
                finally:
                    config = args[0] if args else None
                    payload = None
                    try:
                        if result is not None:
                            if isinstance(result, tuple) and len(result) > 0:
                                payload = result[0]
                            else:
                                payload = result
                    except (TypeError, AttributeError) as e:
                        logger.warning(
                            "[CHECKPOINTER] Failed to extract payload from aget_tuple result: %s",
                            type(e).__name__
                        )
                        payload = None
                    except Exception as e:
                        logger.warning(
                            "[CHECKPOINTER] Unexpected error extracting payload from aget_tuple: %s",
                            type(e).__name__
                        )
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
                    await self._ensure_pool_open()
                    if len(args) > 1:
                        payload = _compact_payload(
                            args[1],
                            max_messages=max_messages,
                            max_chars=max_chars,
                            drop_base64=drop_base64,
                        )
                        args = (args[0], payload, *args[2:])
                    return await self._base.aput(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    payload = args[1] if len(args) > 1 else None
                    _log_if_slow(
                        "aput", _t0, config, payload=payload, slow_threshold_s=slow_threshold_s
                    )

            async def aput_writes(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    await self._ensure_pool_open()
                    if len(args) > 1:
                        payload = _compact_payload(
                            args[1],
                            max_messages=max_messages,
                            max_chars=max_chars,
                            drop_base64=drop_base64,
                        )
                        args = (args[0], payload, *args[2:])
                    return await self._base.aput_writes(*args, **kwargs)
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
                    return self._base.get_tuple(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    _log_if_slow(
                        "get_tuple", _t0, config, payload=None, slow_threshold_s=slow_threshold_s
                    )

            def put(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    return self._base.put(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    _log_if_slow(
                        "put", _t0, config, payload=None, slow_threshold_s=slow_threshold_s
                    )

            def put_writes(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    return self._base.put_writes(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    _log_if_slow(
                        "put_writes", _t0, config, payload=None, slow_threshold_s=slow_threshold_s
                    )
            
            # Delegate any other methods/properties to base
            def __getattr__(self, name: str) -> Any:
                return getattr(self._base, name)

        # Create instrumented wrapper around AsyncPostgresSaver
        checkpointer = InstrumentedAsyncPostgresSaver(base_checkpointer, pool)

        logger.info("AsyncPostgresSaver checkpointer initialized successfully")
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
        
        # Fail-fast check: verify async methods exist (critical for LangGraph ainvoke)
        if not hasattr(_checkpointer, "aget_tuple"):
            logger.error(
                "CRITICAL: Postgres checkpointer missing aget_tuple method! "
                "LangGraph ainvoke() will fail with NotImplementedError. "
                "Falling back to MemorySaver."
            )
            _checkpointer = SerializableMemorySaver()
            checkpointer_type = CheckpointerType.MEMORY
        elif not callable(getattr(_checkpointer, "aget_tuple", None)):
            logger.error(
                "CRITICAL: Postgres checkpointer.aget_tuple is not callable! "
                "LangGraph ainvoke() will fail. Falling back to MemorySaver."
            )
            _checkpointer = SerializableMemorySaver()
            checkpointer_type = CheckpointerType.MEMORY
        else:
            logger.debug("Postgres checkpointer verified: async methods available")
            
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
    global _checkpointer, _checkpointer_type
    
    try:
        # Ensure checkpointer is initialized
        checkpointer = get_checkpointer()
        
        # For AsyncPostgresSaver, verify async methods exist and pool is open
        if _checkpointer_type == CheckpointerType.POSTGRES:
            # Verify checkpointer has async methods (fail-fast check)
            if not hasattr(checkpointer, "aget_tuple"):
                logger.error(
                    "CRITICAL: Postgres checkpointer missing aget_tuple method! "
                    "This will cause NotImplementedError. Check checkpointer implementation."
                )
                return False
            
            aget_tuple_method = getattr(checkpointer, "aget_tuple", None)
            if not callable(aget_tuple_method):
                logger.error(
                    "CRITICAL: Postgres checkpointer.aget_tuple is not callable! "
                    "This will cause NotImplementedError. Check checkpointer implementation."
                )
                return False
            
            # If checkpointer has _pool attribute, ensure it's open
            if hasattr(checkpointer, "_pool"):
                pool = checkpointer._pool
                # Check if pool is closed (not opened yet)
                if hasattr(pool, "_closed") and pool._closed:
                    logger.info("Opening AsyncPostgresSaver checkpointer pool...")
                    await pool.open(wait=True, timeout=10.0)
                    logger.info("AsyncPostgresSaver checkpointer pool opened successfully")
                elif hasattr(pool, "open"):
                    # Pool might be open, but verify by attempting to open it
                    # (opening an already open pool is safe and idempotent)
                    try:
                        await pool.open(wait=True, timeout=10.0)
                        logger.info("AsyncPostgresSaver checkpointer pool is open and ready")
                    except Exception as e:
                        logger.debug("Pool open check: %s", e)
                        # Pool might already be open, which is fine
                        logger.info("AsyncPostgresSaver checkpointer pool is ready")
            
            logger.info("AsyncPostgresSaver checkpointer initialized and verified (async methods available)")
            return True
        
        # For MemorySaver or other non-pool checkpointers, warmup is not needed
        logger.debug("Checkpointer warmup not needed (using %s)", _checkpointer_type)
        return True
        
    except Exception as e:
        logger.warning("Checkpointer warmup failed: %s", e)
        return False


async def get_pool_health() -> dict[str, Any] | None:
    """Get connection pool health status.
    
    Returns:
        dict with pool health metrics:
        {
            "available": int,  # Available connections
            "max": int,  # Maximum pool size
            "utilization_percent": float,  # Utilization percentage
            "is_exhausted": bool,  # True if >80% utilized
        }
        None if pool is not available or not initialized
    """
    global _pool_instance
    if _pool_instance is None:
        return None
    
    pool = _pool_instance
    
    try:
        # Try to get pool stats
        # psycopg_pool.AsyncConnectionPool has different attributes depending on version
        available = None
        max_size = None
        
        # Try common attributes
        if hasattr(pool, "get_stats"):
            stats = pool.get_stats()
            available = stats.get("pool_available", None)
            max_size = stats.get("pool_max", None)
        elif hasattr(pool, "_pool"):
            # Internal pool object
            internal_pool = pool._pool
            if hasattr(internal_pool, "get_stats"):
                stats = internal_pool.get_stats()
                available = stats.get("pool_available", None)
                max_size = stats.get("pool_max", None)
        
        # Fallback: try to infer from pool attributes
        if available is None or max_size is None:
            if hasattr(pool, "min_size") and hasattr(pool, "max_size"):
                max_size = pool.max_size
                # Estimate available (this is approximate)
                # In practice, we'd need to check pool internals
                available = max_size  # Conservative estimate
        
        if available is not None and max_size is not None:
            utilization_percent = ((max_size - available) / max_size) * 100 if max_size > 0 else 0.0
            is_exhausted = utilization_percent > 80.0
            
            return {
                "available": available,
                "max": max_size,
                "utilization_percent": round(utilization_percent, 2),
                "is_exhausted": is_exhausted,
            }
        
        return None
        
    except Exception as e:
        logger.debug("[CHECKPOINTER] Failed to get pool health: %s", e)
        return None


async def shutdown_checkpointer_pool() -> None:
    """Gracefully close checkpointer pool on application shutdown.
    
    This should be called during application shutdown to properly close
    database connections and avoid connection leaks.
    """
    global _pool_instance
    if _pool_instance is None:
        return
    
    pool = _pool_instance
    _pool_instance = None
    
    try:
        import asyncio
        if hasattr(pool, "close"):
            # Give active connections time to finish (max 5 seconds)
            await asyncio.wait_for(pool.close(), timeout=5.0)
            logger.info("[CHECKPOINTER] Pool closed gracefully")
        elif hasattr(pool, "wait"):
            # Some pool implementations use wait() instead
            await asyncio.wait_for(pool.wait(), timeout=5.0)
            logger.info("[CHECKPOINTER] Pool closed gracefully")
    except asyncio.TimeoutError:
        logger.warning("[CHECKPOINTER] Pool close timed out, forcing shutdown")
    except Exception as e:
        logger.warning("[CHECKPOINTER] Error closing pool: %s", e)