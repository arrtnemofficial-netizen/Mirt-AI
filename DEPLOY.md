# 🚀 Deployment Guide

This guide describes how to deploy Mirt-AI to production environments (Railway, Docker, VPS).

## 🛠 Prerequisites

- Python 3.11+
- Redis (for Celery)
- PostgreSQL (Supabase)
- OpenAI/OpenRouter API Keys

## 🚂 Railway Deployment

Railway detects the `Procfile` or allow you to specify start commands in `railway.toml`.

### Services

You need to deploy 3 separate services (or 1 service with multiple processes if using Docker Compose, but on Railway separate services are strictly recommended for scaling).

#### 1. Web API (HTTP)
Handles Webhooks (Telegram, ManyChat) and API requests.
- **Command:**
  ```bash
  uvicorn src.server.main:app --host 0.0.0.0 --port $PORT
  ```

#### 2. Celery Worker (Background Tasks)
Processes LLM requests, CRM updates, and heavy logic.
- **Command:**
  ```bash
  celery -A src.workers.celery_app worker --loglevel=info --concurrency=4
  ```
- **Scale:** Can be scaled horizontally (multiple replicas).

#### 3. Celery Beat (Scheduler)
Schedules periodic tasks (Follow-ups, Summarization).
- **Command:**
  ```bash
  celery -A src.workers.celery_app beat --loglevel=info --schedule /tmp/celerybeat-schedule
  ```
- **Scale:** **MUST be a singleton** (only 1 replica), otherwise tasks will duplicate.

## 🐳 Docker Compose (Local/VPS)

```yaml
version: '3.8'

services:
  api:
    build: .
    command: uvicorn src.server.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    ports:
      - "8000:8000"

  worker:
    build: .
    command: celery -A src.workers.celery_app worker --loglevel=info
    env_file: .env
    depends_on:
      - redis

  beat:
    build: .
    command: celery -A src.workers.celery_app beat --loglevel=info
    env_file: .env
    depends_on:
      - redis

  redis:
    image: redis:alpine
```

## 🧪 Verification

1. Check **Worker logs**: Should see `[tasks] . src.workers.tasks...`
2. Check **Beat logs**: Should see `Beat: Starting...`
3. Send `/start` to Telegram bot -> Logs should show `Received message` in API and task processing in Worker.
