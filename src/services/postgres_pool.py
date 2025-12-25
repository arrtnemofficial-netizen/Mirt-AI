"""PostgreSQL connection pool manager for direct database access."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

try:
    from psycopg_pool import AsyncConnectionPool
    from psycopg import AsyncConnection
except ImportError:
    AsyncConnectionPool = None  # type: ignore
    AsyncConnection = None  # type: ignore

from src.conf.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[AsyncConnectionPool] = None


def get_postgres_url() -> str:
    """Get PostgreSQL connection URL from environment."""
    # Priority: DATABASE_URL > POSTGRES_URL
    url = settings.DATABASE_URL or getattr(settings, "POSTGRES_URL", "")
    
    if not url:
        raise ValueError(
            "DATABASE_URL or POSTGRES_URL must be set for PostgreSQL connection"
        )
    
    return url


async def get_postgres_pool() -> AsyncConnectionPool:
    """
    Get or create PostgreSQL connection pool (singleton).
    
    Returns:
        AsyncConnectionPool instance
        
    Raises:
        ValueError: If psycopg_pool is not installed
        RuntimeError: If pool creation fails
    """
    global _pool
    
    if _pool is not None:
        return _pool
    
    if AsyncConnectionPool is None:
        raise ValueError(
            "psycopg_pool is not installed. Install it with: pip install 'psycopg[binary,pool]'"
        )
    
    url = get_postgres_url()
    
    # Pool configuration
    min_size = getattr(settings, "POSTGRES_POOL_MIN_SIZE", 1)
    max_size = getattr(settings, "POSTGRES_POOL_MAX_SIZE", 10)
    max_idle = getattr(settings, "POSTGRES_POOL_MAX_IDLE", 30)
    
    try:
        _pool = AsyncConnectionPool(
            url,
            min_size=min_size,
            max_size=max_size,
            max_idle=max_idle,
        )
        
        logger.info(
            "PostgreSQL connection pool created: min=%d, max=%d, max_idle=%d",
            min_size,
            max_size,
            max_idle,
        )
        
        return _pool
    except Exception as e:
        logger.error("Failed to create PostgreSQL connection pool: %s", e)
        raise RuntimeError(f"Failed to create PostgreSQL pool: {e}") from e


async def close_postgres_pool() -> None:
    """Close PostgreSQL connection pool."""
    global _pool
    
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed")


async def get_postgres_connection() -> AsyncConnection:
    """
    Get a connection from the pool.
    
    Returns:
        AsyncConnection from pool
    """
    pool = await get_postgres_pool()
    return await pool.getconn()


async def health_check() -> bool:
    """Check if PostgreSQL connection is healthy."""
    try:
        pool = await get_postgres_pool()
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error("PostgreSQL health check failed: %s", e)
        return False

