# Database Access Rules

## Overview

This document defines the access patterns for PostgreSQL in the Mirt-AI codebase.

## The Golden Rule

| Context | Allowed Pattern | Reason |
|---------|-----------------|--------|
| **FastAPI endpoints** | `await get_postgres_pool()` + async | Non-blocking event loop |
| **Celery workers** | `psycopg.connect()` sync | Separate process, blocking OK |
| **CLI scripts** | `psycopg.connect()` sync | One-off execution |

---

## ❌ Anti-Patterns (NEVER DO THIS)

### 1. Sync connect in async handler
```python
# BAD - blocks event loop!
@router.get("/health")
async def health_check():
    with psycopg.connect(url) as conn:  # ❌ BLOCKING!
        cur.execute("SELECT 1")
```

### 2. asyncio.run() in web context
```python
# BAD - nested event loop error!
async def handler():
    result = asyncio.run(some_async_func())  # ❌ CRASH!
```

---

## ✅ Correct Patterns

### FastAPI (async pool)
```python
from src.services.storage import get_postgres_pool

@router.get("/health")
async def health_check():
    pool = await get_postgres_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
            result = await cur.fetchone()
    return {"status": "ok"}
```

### Celery (sync)
```python
from src.services.storage import get_postgres_url
import psycopg

@celery.task
def process_message():
    with psycopg.connect(get_postgres_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()
    return result
```

### Calling async from Celery
```python
from src.workers.sync_utils import run_sync

@celery.task
def my_task():
    # wrap async call for sync context
    result = run_sync(some_async_function())
    return result
```

---

## File Ownership

| Directory | Allowed DB Access |
|-----------|-------------------|
| `src/server/` | Async pool ONLY |
| `src/workers/` | Sync OK |
| `src/services/` | Depends on caller |
| `scripts/` | Sync OK |

---

## Enforcement

Run `grep -r "psycopg.connect" src/server/` — should return 0 results.
