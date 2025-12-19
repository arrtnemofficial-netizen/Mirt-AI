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

import asyncio
import logging
import os
import time
from enum import Enum
from typing import TYPE_CHECKING, Any
import json

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
    database_url = (
        os.getenv("DATABASE_URL_POOLER")
        or os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")
    )

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
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        # Setup tables first using sync connection with prepare_threshold=None
        # None completely disables prepared statements (vs 0 which means "after 0 uses")
        setup_conn = psycopg.connect(database_url, autocommit=True, prepare_threshold=None)
        try:
            temp_checkpointer = PostgresSaver(setup_conn)
            temp_checkpointer.setup()
        finally:
            setup_conn.close()

        # Create async pool with prepare_threshold=None
        # CRITICAL for Supabase PgBouncer which doesn't support prepared statements
        # None = never use prepared statements (0 still creates them after 0 uses)
        #
        # Also configure for Supabase connection limits:
        # - max_idle=30: Close idle connections before Supabase does (avoids SSL errors)
        # - check: Verify connection is alive before use

        async def check_connection(conn):
            """Check if connection is still alive before returning from pool."""
            try:
                await conn.execute("SELECT 1")
            except Exception:
                raise  # Connection is dead, pool will discard it

        def _env_float(name: str, default: float) -> float:
            raw = (os.getenv(name, "") or "").strip()
            if not raw:
                return default
            try:
                return float(raw)
            except Exception:
                return default

        def _env_int(name: str, default: int) -> int:
            raw = (os.getenv(name, "") or "").strip()
            if not raw:
                return default
            try:
                return int(float(raw))
            except Exception:
                return default

        pool_min_size = _env_int("CHECKPOINTER_POOL_MIN_SIZE", 1)
        pool_max_size = _env_int("CHECKPOINTER_POOL_MAX_SIZE", 5)
        pool_timeout_s = _env_float("CHECKPOINTER_POOL_TIMEOUT_SECONDS", 15.0)
        pool_max_idle_s = _env_float("CHECKPOINTER_POOL_MAX_IDLE_SECONDS", 120.0)
        connect_timeout_s = _env_float("CHECKPOINTER_CONNECT_TIMEOUT_SECONDS", 10.0)

        statement_timeout_ms = _env_int("CHECKPOINTER_STATEMENT_TIMEOUT_MS", 8000)
        lock_timeout_ms = _env_int("CHECKPOINTER_LOCK_TIMEOUT_MS", 2000)

        if pool_min_size < 0:
            pool_min_size = 0
        if pool_max_size < 1:
            pool_max_size = 1
        if pool_min_size > pool_max_size:
            pool_min_size = pool_max_size

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

        slow_threshold_s = 1.0
        try:
            slow_threshold_s = float(os.getenv("CHECKPOINTER_SLOW_LOG_SECONDS", "1.0") or "1.0")
        except Exception:
            slow_threshold_s = 1.0

        def _extract_thread_id(config: Any | None) -> str:
            if not isinstance(config, dict):
                return "?"
            configurable = config.get("configurable")
            if isinstance(configurable, dict):
                thread_id = configurable.get("thread_id")
                if thread_id:
                    return str(thread_id)
            return "?"

        def _checkpoint_stats(obj: Any) -> tuple[int | None, int | None]:
            """Return (json_bytes, messages_count) best-effort."""
            json_bytes: int | None = None
            messages_count: int | None = None
            try:
                s = json.dumps(obj, ensure_ascii=False, default=str)
                json_bytes = len(s.encode("utf-8", errors="ignore"))
            except Exception:
                json_bytes = None

            try:
                if isinstance(obj, dict):
                    # Common internal shapes used by LangGraph checkpointers.
                    for k in ("channel_values", "values", "state"):
                        v = obj.get(k)
                        if isinstance(v, dict) and "messages" in v:
                            mv = v.get("messages")
                            if isinstance(mv, list):
                                messages_count = len(mv)
                                break
                    if messages_count is None and isinstance(obj.get("messages"), list):
                        messages_count = len(obj.get("messages"))
            except Exception:
                messages_count = None

            return json_bytes, messages_count

        def _compact_payload(payload: Any) -> Any:
            if not isinstance(payload, dict):
                return payload

            compact = payload
            messages = payload.get("messages")
            if isinstance(messages, list):
                max_messages = _env_int("CHECKPOINTER_MAX_MESSAGES", 200)
                if max_messages > 0 and len(messages) > max_messages:
                    messages = messages[-max_messages:]

                max_chars = _env_int("CHECKPOINTER_MAX_MESSAGE_CHARS", 4000)
                if max_chars > 0:
                    trimmed: list[Any] = []
                    for m in messages:
                        if isinstance(m, dict):
                            content = m.get("content")
                            if isinstance(content, str) and len(content) > max_chars:
                                m = {**m, "content": content[:max_chars] + "...[truncated]"}
                        trimmed.append(m)
                    messages = trimmed

                compact = {**compact, "messages": messages}

            raw_drop = (os.getenv("CHECKPOINTER_DROP_BASE64", "true") or "true").strip().lower()
            drop_base64 = raw_drop in {"1", "true", "yes"}
            if drop_base64:
                image_url = compact.get("image_url")
                if isinstance(image_url, str) and len(image_url) > 2000:
                    if image_url.startswith("data:") or "base64" in image_url:
                        compact = {**compact, "image_url": "<base64_stripped>"}

            return compact

        def _log_if_slow(op: str, started_at: float, config: Any | None, *, payload: Any | None = None) -> None:
            elapsed = time.perf_counter() - started_at
            if elapsed < slow_threshold_s:
                return
            thread_id = _extract_thread_id(config)
            level = logging.WARNING if elapsed >= max(10.0, slow_threshold_s * 10.0) else logging.INFO
            extra = ""
            if payload is not None:
                size_b, msg_n = _checkpoint_stats(payload)
                if size_b is not None or msg_n is not None:
                    extra = f" size_bytes={size_b} messages={msg_n}"
            logger.log(level, "[CHECKPOINTER] %s thread_id=%s took %.2fs%s", op, thread_id, elapsed, extra)

        class InstrumentedAsyncPostgresSaver(AsyncPostgresSaver):
            async def _ensure_pool_open(self) -> None:
                pool = getattr(self, "pool", None) or getattr(self, "conn", None)
                if pool is None:
                    return
                if not hasattr(pool, "open"):
                    return
                try:
                    try:
                        await pool.open(wait=True)
                    except TypeError:
                        await pool.open()
                    logger.info("[CHECKPOINTER] pool opened on demand")
                except Exception as exc:
                    msg = str(exc).lower()
                    if "already" in msg and "open" in msg:
                        return
                    logger.warning("[CHECKPOINTER] pool open failed on demand: %s", exc)

            async def aget_tuple(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    await self._ensure_pool_open()
                    result = await super().aget_tuple(*args, **kwargs)
                    return result
                finally:
                    config = args[0] if args else None
                    payload = None
                    try:
                        if isinstance(locals().get("result"), tuple) and len(locals()["result"]) > 0:
                            payload = locals()["result"][0]
                        else:
                            payload = locals().get("result")
                    except Exception:
                        payload = None
                    _log_if_slow("aget_tuple", _t0, config, payload=payload)

            async def aput(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    await self._ensure_pool_open()
                    if len(args) > 1:
                        payload = _compact_payload(args[1])
                        args = (args[0], payload, *args[2:])
                    return await super().aput(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    payload = args[1] if len(args) > 1 else None
                    _log_if_slow("aput", _t0, config, payload=payload)

            async def aput_writes(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    await self._ensure_pool_open()
                    if len(args) > 1:
                        payload = _compact_payload(args[1])
                        args = (args[0], payload, *args[2:])
                    return await super().aput_writes(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    payload = args[1] if len(args) > 1 else None
                    _log_if_slow("aput_writes", _t0, config, payload=payload)

            def get_tuple(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    return super().get_tuple(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    _log_if_slow("get_tuple", _t0, config)

            def put(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    return super().put(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    _log_if_slow("put", _t0, config)

            def put_writes(self, *args: Any, **kwargs: Any):
                _t0 = time.perf_counter()
                try:
                    return super().put_writes(*args, **kwargs)
                finally:
                    config = args[0] if args else None
                    _log_if_slow("put_writes", _t0, config)

        checkpointer = InstrumentedAsyncPostgresSaver(pool)

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
        def _sanitize_db_url(url: str) -> str:
            try:
                # Keep scheme/host/db, strip password/userinfo.
                # postgresql://user:pass@host:5432/db -> postgresql://***@host:5432/db
                from urllib.parse import urlsplit, urlunsplit

                parts = urlsplit(url)
                netloc = parts.netloc
                if "@" in netloc:
                    netloc = "***@" + netloc.split("@", 1)[1]
                return urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
            except Exception:
                return "<unavailable>"

        raw_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
        logger.error(
            "Failed to create PostgreSQL checkpointer: %s (db_url=%s)",
            e,
            _sanitize_db_url(raw_url) if raw_url else "<empty>",
            exc_info=True,
        )
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

    # Import settings for proper .env loading via pydantic_settings
    from src.conf.config import settings as app_settings

    # 1) Explicit override via LANGGRAPH_CHECKPOINTER (settings/env)
    #    This has priority over auto-detection when checkpointer_type is not passed.
    if checkpointer_type is None:
        raw_choice = getattr(app_settings, "LANGGRAPH_CHECKPOINTER", "auto").lower()

        if raw_choice in {"memory", "postgres", "redis"}:
            if raw_choice == "memory":
                checkpointer_type = CheckpointerType.MEMORY
            elif raw_choice == "postgres":
                checkpointer_type = CheckpointerType.POSTGRES
            elif raw_choice == "redis":
                checkpointer_type = CheckpointerType.REDIS
            logger.info("Checkpointer overridden via LANGGRAPH_CHECKPOINTER=%s", raw_choice)

    # 2) Auto-detect type if still not specified
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

    # If Postgres saver construction failed we may have fallen back to memory.
    actual_type = checkpointer_type
    if checkpointer_type == CheckpointerType.POSTGRES:
        if isinstance(_checkpointer, MemorySaver):
            actual_type = CheckpointerType.MEMORY
            logger.warning(
                "Postgres checkpointer requested but fallback to MemorySaver occurred. "
                "Persistence is DISABLED until Postgres checkpointer is fixed."
            )

    logger.info("Checkpointer selected: %s", actual_type)

    _checkpointer_type = actual_type
    return _checkpointer


def get_current_checkpointer_type() -> CheckpointerType | None:
    """Get the type of the current checkpointer."""
    return _checkpointer_type


async def warmup_checkpointer_pool() -> bool:
    raw_enabled = (os.getenv("CHECKPOINTER_WARMUP", "true") or "true").strip().lower()
    if raw_enabled in {"0", "false", "no"}:
        return True

    try:
        timeout_s = float(os.getenv("CHECKPOINTER_WARMUP_TIMEOUT_SECONDS", "15") or "15")
    except Exception:
        timeout_s = 15.0

    checkpointer = get_checkpointer()
    pool = getattr(checkpointer, "pool", None)
    if pool is None:
        return False

    _t0 = time.perf_counter()
    try:
        # Prefer wait=True so min_size connections are established during warmup,
        # preventing the first request from paying the connect handshake cost.
        try:
            await asyncio.wait_for(pool.open(wait=True), timeout=timeout_s)
        except TypeError:
            # Older psycopg_pool versions may not support wait=...
            await asyncio.wait_for(pool.open(), timeout=timeout_s)
    except Exception as e:
        logger.warning(
            "[CHECKPOINTER] pool warmup failed after %.2fs: %s",
            time.perf_counter() - _t0,
            e,
        )
        return False

    logger.info("[CHECKPOINTER] pool open triggered in %.2fs", time.perf_counter() - _t0)

    async def _preflight() -> None:
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")

    _t1 = time.perf_counter()
    try:
        await asyncio.wait_for(_preflight(), timeout=timeout_s)
    except Exception as e:
        logger.warning(
            "[CHECKPOINTER] pool preflight failed after %.2fs: %s",
            time.perf_counter() - _t1,
            e,
        )
        return False

    logger.info("[CHECKPOINTER] pool preflight ok in %.2fs", time.perf_counter() - _t1)
    return True


def is_persistent() -> bool:
    """Check if the current checkpointer is persistent (survives restarts)."""
    return _checkpointer_type in (CheckpointerType.POSTGRES, CheckpointerType.REDIS)
