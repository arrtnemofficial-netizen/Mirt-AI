# 🚀 Deployment Guide (Railway & Docker)

> **Version:** 5.0 (Implementation)  
> **Source:** `Dockerfile` & `railway.toml`  
> **Updated:** 20 December 2025

---

## 🚂 Railway Configuration

MIRT AI is optimized for Railway using **Nixpacks**.

### Service: `web` (FastAPI)
- **Start Command:**
  ```bash
  uvicorn src.server.main:app --host 0.0.0.0 --port $PORT
  ```
- **Healthcheck:** `/health` (Timeout: 30s)

### Service: `worker` (Celery)
- **Start Command:**
  ```bash
  celery -A src.workers.celery_app worker -l info -c 4 -Q llm,webhooks,followups,crm,summarization,default
  ```
- **Critical Env Vars:**
  - `CELERY_ENABLED=true`
  - `REDIS_TLS=false` (Railway Internal Redis usually doesn't need TLS, external does)

### Service: `beat` (Scheduler)
- **Start Command:**
  ```bash
  celery -A src.workers.celery_app beat -l info
  ```

---

## 🐳 Docker Deployment

Based on standard `python:3.11-slim` image.

### Recommended `docker-compose.yml`

```yaml
services:
  web:
    build: .
    command: uvicorn src.server.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    ports: ["8000:8000"]
    depends_on: [redis, postgres]

  worker:
    build: .
    command: celery -A src.workers.celery_app worker -l info -Q llm,webhooks,followups,crm,summarization,default
    env_file: .env
    depends_on: [redis]

  beat:
    build: .
    command: celery -A src.workers.celery_app beat -l info
    env_file: .env
    depends_on: [redis]
```

---

## 🔑 Critical Environment Variables

These variables are actively used in `src/conf/config.py`:

| Variable | Required? | Description |
|:---------|:----------|:------------|
| `PUBLIC_BASE_URL` | YES | Used for webhook verification logic. |
| `OPENAI_API_KEY` | YES | Core intelligence (GPT-4o). |
| `DATABASE_URL_POOLER` | YES | Connection pooling for Checkpointer (Supavisor). |
| `REDIS_URL` | YES | Celery Broker & Debounce Lock. |
| `MANYCHAT_API_KEY` | YES | For sending responses. |
| `MANYCHAT_PUSH_MODE` | NO | Set `true` for async processing. |
| `SITNIKS_API_KEY` | NO | If CRM integration is enabled. |

---

## 🛡️ SSL & Security

- **Webhooks:** Telegram REQUIRE HTTPS.
- **ManyChat:** Requires a valid SSL certificate.
- **Railway:** Provides automatic SSL for `*.up.railway.app` domains.

---
