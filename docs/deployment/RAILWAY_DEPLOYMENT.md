# Railway Deployment Guide

> 📚 **Центральний індекс:** [../DOCUMENTATION.md](../DOCUMENTATION.md)

## Overview

MIRT AI requires **3 separate services** on Railway:
1. **Main App** - FastAPI webhook server
2. **Worker** - Celery worker for background tasks
3. **Beat** - Celery Beat scheduler for periodic tasks

## Service Configuration

### 1. Main App Service

**Service Name:** `beat` (or `mirt-ai-main`)

**Start Command:**
```bash
python src/run.py
```

**Environment Variables:**
- All variables from `.env` (see [Production Environment Setup](#environment-variables))
- **Required:**
  - `DATABASE_URL` - PostgreSQL connection string
  - `REDIS_URL` - Redis connection string
  - `OPENAI_API_KEY` - OpenAI API key for GPT-5.1
  - `MANYCHAT_API_KEY` - ManyChat API key
  - `TELEGRAM_BOT_TOKEN` - Telegram bot token
  - `PUBLIC_BASE_URL` - Public URL (e.g., `https://mirt-ai-production.up.railway.app`)

**Health Check URL:**
```
GET /health
```

**Preflight Check:**
```
GET /health/preflight
```

### 2. Worker Service

**Service Name:** `Worker` (or `mirt-ai-worker`)

**Start Command:**
```bash
python scripts/run_worker.py
```

**⚠️ CRITICAL:** Do NOT use `python src/run.py` - this starts the web server, not the worker!

**Environment Variables:**
- Same as Main App (all variables are shared)
- **Required:**
  - `DATABASE_URL` - For database access
  - `REDIS_URL` - For Celery broker/backend
  - `CELERY_ENABLED=true` - Must be enabled

**What it does:**
- Processes background tasks (summarization, follow-ups, memory cleanup)
- Listens to queues: `default`, `summarization`, `followups`, `crm`, `webhooks`, `llm`

**Verification:**
- Check logs for startup banner: `MIRT AI - CELERY WORKER`
- Check `GET /health/workers` from Main App - should show `active_count > 0`

### 3. Beat Service

**Service Name:** `beat` (or `mirt-ai-beat`)

**Start Command:**
```bash
python scripts/run_beat.py
```

**⚠️ CRITICAL:** Do NOT use `python src/run.py` - this starts the web server, not the scheduler!

**Environment Variables:**
- Same as Main App (all variables are shared)
- **Required:**
  - `REDIS_URL` - For Celery broker
  - `CELERY_ENABLED=true` - Must be enabled

**What it does:**
- Schedules periodic tasks:
  - `followups-check-15min` - Check for follow-up messages every 15 minutes
  - `summarization-check-1h` - Check for summarization every hour
  - `memory-cleanup-expired-daily` - Cleanup expired memories daily at 3:00 UTC

**Verification:**
- Check logs for startup banner: `MIRT AI - CELERY BEAT`
- Check logs for "Scheduled Tasks:" list
- Check `GET /health/workers` from Main App - should show `scheduled_tasks` list

## Environment Variables

### Required for All Services

```bash
# Database
DATABASE_URL="postgresql://user:pass@host:port/db"
DATABASE_PUBLIC_URL="postgresql://user:pass@host:port/db"

# Redis (for Celery)
REDIS_URL="redis://default:pass@host:port"

# LLM
OPENAI_API_KEY="sk-proj-..."
AI_MODEL="gpt-5.1"
LLM_PROVIDER="openai"
LLM_MODEL_GPT="gpt-5.1"
LLM_MODEL_VISION="gpt-5.1"

# Observability (for llm_traces table)
ENABLE_OBSERVABILITY="true"

# Celery
CELERY_ENABLED="true"
CELERY_CONCURRENCY="4"
CELERY_MAX_TASKS_PER_CHILD="100"

# ManyChat
MANYCHAT_API_KEY="..."
MANYCHAT_API_URL="https://api.manychat.com"

# Telegram
TELEGRAM_BOT_TOKEN="..."
MANAGER_BOT_TOKEN="..."
MANAGER_CHAT_ID="..."

# CRM (Sitniks)
SNITKIX_API_URL="https://crm.sitniks.com"
SNITKIX_API_KEY="..."
ENABLE_CRM_INTEGRATION="true"

# Public URL
PUBLIC_BASE_URL="https://mirt-ai-production.up.railway.app"
```

### Optional but Recommended

```bash
# Memory System thresholds
MEMORY_MIN_IMPORTANCE="0.6"
MEMORY_MIN_SURPRISE="0.4"

# Checkpointer
CHECKPOINTER_WARMUP="true"
CHECKPOINTER_POOL_MIN_SIZE="0"
CHECKPOINTER_POOL_MAX_SIZE="2"

# Retention
SUMMARY_RETENTION_DAYS="3"
FOLLOWUP_DELAYS_HOURS="24,72"
```

## Deployment Checklist

### Before Deployment

- [ ] All 3 services created on Railway
- [ ] Environment variables set for all services
- [ ] Start Commands configured correctly:
  - [ ] Main App: `python src/run.py`
  - [ ] Worker: `python scripts/run_worker.py`
  - [ ] Beat: `python scripts/run_beat.py`
- [ ] Database migrations applied
- [ ] Redis instance provisioned and accessible

### After Deployment

1. **Check Main App:**
   ```bash
   curl https://your-app.railway.app/health/preflight
   ```
   Should return `"status": "ok"`

2. **Check Worker Logs:**
   - Look for: `MIRT AI - CELERY WORKER Starting`
   - Look for: `✓ Redis connection: OK`
   - Look for: `Registered Tasks:` list

3. **Check Beat Logs:**
   - Look for: `MIRT AI - CELERY BEAT Starting`
   - Look for: `✓ Redis connection: OK`
   - Look for: `Scheduled Tasks:` list

4. **Verify Workers are Active:**
   ```bash
   curl https://your-app.railway.app/health/workers
   ```
   Should show `"active_count": 1` or more

5. **Verify Scheduled Tasks:**
   ```bash
   curl https://your-app.railway.app/health/workers
   ```
   Should show `scheduled_tasks` array with 3 tasks

6. **Test Database Tables:**
   - Send a test message via ManyChat/Telegram
   - Check `users` table - should have new row
   - Check `messages` table - should have new rows
   - After payment proof - check `orders` and `order_items` tables

## Troubleshooting

### Tables Not Populating

**Problem:** `users`, `orders`, `order_items`, `llm_traces`, `mirt_profiles`, `mirt_memories` are empty.

**Solutions:**

1. **Check `/health/preflight`:**
   ```bash
   curl https://your-app.railway.app/health/preflight
   ```
   Look for `recommendations` array - it will tell you what's wrong.

2. **`users` table not filling:**
   - Check that `user_id` is passed in message metadata
   - Check logs for `_update_user_interaction` calls
   - Verify `DATABASE_URL` is correct

3. **`orders` / `order_items` not filling:**
   - Orders are created **only after payment proof** (screenshot/receipt)
   - Check `payment_node` logs for `_persist_order_and_queue_crm` calls
   - Verify `has_real_proof` is `True` in state

4. **`llm_traces` not filling:**
   - Check `ENABLE_OBSERVABILITY="true"` is set
   - Check `/health/observability` endpoint
   - Verify `DATABASE_URL` is correct

5. **`mirt_profiles` / `mirt_memories` not filling:**
   - Check `DATABASE_URL` is configured
   - Check `/health/memory` endpoint
   - Verify memory thresholds: `MEMORY_MIN_IMPORTANCE`, `MEMORY_MIN_SURPRISE`
   - Check that `memory_context_node` is being called

6. **`mirt_memory_summaries` not filling:**
   - Check that Beat service is running
   - Check that `summarization-check-1h` scheduled task exists
   - Check Beat logs for task execution

### Workers Not Starting

**Problem:** `GET /health/workers` shows `"active_count": 0`

**Solutions:**

1. **Check Worker service Start Command:**
   - Must be: `python scripts/run_worker.py`
   - NOT: `python src/run.py`

2. **Check Worker logs:**
   - Look for startup banner
   - Look for Redis connection errors
   - Look for import errors

3. **Check Redis:**
   ```bash
   curl https://your-app.railway.app/health/workers
   ```
   Look for `"redis": {"status": "ok"}`

4. **Check environment variables:**
   - `CELERY_ENABLED="true"`
   - `REDIS_URL` is set and accessible

### Beat Not Scheduling Tasks

**Problem:** Scheduled tasks (followups, summarization) not running

**Solutions:**

1. **Check Beat service Start Command:**
   - Must be: `python scripts/run_beat.py`
   - NOT: `python src/run.py`

2. **Check Beat logs:**
   - Look for startup banner
   - Look for "Scheduled Tasks:" list
   - Should show 3 tasks: `followups-check-15min`, `summarization-check-1h`, `memory-cleanup-expired-daily`

3. **Check Redis:**
   - Beat needs Redis to store schedule state
   - Verify `REDIS_URL` is accessible

4. **Check `beat_schedule` in code:**
   - Verify `src/workers/celery_app.py` has `beat_schedule` configured
   - Verify tasks are registered in `include` list

### LLM Using Wrong Model

**Problem:** Logs show `gpt-4o-mini` instead of `gpt-5.1`

**Solutions:**

1. **Check environment variables:**
   ```bash
   AI_MODEL="gpt-5.1"
   LLM_PROVIDER="openai"
   LLM_MODEL_GPT="gpt-5.1"
   ```

2. **Check startup logs:**
   - Look for: `LLM Configuration: AI_MODEL=gpt-5.1`
   - Should NOT show fallback warnings

3. **Check `/health/preflight`:**
   - Look for LLM configuration in checks

## Monitoring

### Health Endpoints

- `GET /health` - Basic health check (PostgreSQL, Redis)
- `GET /health/preflight` - **Comprehensive preflight check** (all systems)
- `GET /health/observability` - Observability system status
- `GET /health/memory` - Memory system status
- `GET /health/workers` - Celery workers and beat status

### Recommended Monitoring

1. **Set up Railway health checks:**
   - Main App: `GET /health`
   - Should return `200 OK` with `"status": "ok"`

2. **Monitor `/health/preflight` after deployments:**
   - Should return `"status": "ok"`
   - Check `recommendations` array for warnings

3. **Monitor worker activity:**
   - Check `GET /health/workers` regularly
   - `active_count` should be `>= 1`
   - `scheduled_tasks` should have 3 tasks

4. **Monitor database tables:**
   - Run `scripts/test_prod_tables.py` periodically
   - Check table row counts in production

## Common Mistakes

1. **❌ Using `python src/run.py` for Worker/Beat**
   - This starts the web server, not Celery
   - **✅ Use:** `python scripts/run_worker.py` and `python scripts/run_beat.py`

2. **❌ Not setting `CELERY_ENABLED="true"`**
   - Workers won't start
   - Scheduled tasks won't run

3. **❌ Missing `REDIS_URL`**
   - Celery needs Redis for broker/backend
   - Workers and Beat will fail to start

4. **❌ Missing `ENABLE_OBSERVABILITY="true"`**
   - `llm_traces` table won't be populated
   - No detailed LLM call logging

5. **❌ Wrong `DATABASE_URL`**
   - Tables won't populate
   - Check connection string format

## Next Steps

- [Production Runbook](../operations/PRODUCTION_RUNBOOK.md) - Operational procedures
- [Database Tables Reference](../../docs/DATABASE_TABLES_REFERENCE.md) - Table documentation
- [Celery Operations](../../docs/operations/CELERY.md) - Celery-specific operations

