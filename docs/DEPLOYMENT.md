# Deployment Guide

## 🚂 Railway (Рекомендовано)

### Quick Deploy

```bash
# 1. Railway Dashboard
# New Project → Deploy from GitHub → Select repo

# 2. Railway автоматично знайде:
# - railway.json (конфігурація)
# - Dockerfile (білд)

# 3. Додай Variables (скопіюй з .env.railway)
```

### Конфігураційні файли

| Файл            | Призначення                  |
| --------------- | ---------------------------- |
| `railway.json`  | Основна конфігурація         |
| `railway.toml`  | Альтернативна (TOML)         |
| `nixpacks.toml` | Для авто-білда без Docker    |
| `.env.railway`  | Готові змінні для копіювання |

### Railway Variables

```env
# 🔴 КРИТИЧНІ
OPENROUTER_API_KEY=sk-or-v1-xxx
TELEGRAM_BOT_TOKEN=123:ABC
PUBLIC_BASE_URL=https://your-app.up.railway.app
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_API_KEY=eyJxxx

# 🟡 РЕКОМЕНДОВАНІ
OPENAI_API_KEY=sk-xxx
MANYCHAT_VERIFY_TOKEN=your-token
SENTRY_ENVIRONMENT=production

# 🟢 FEATURE FLAGS
USE_GRAPH_V2=true
USE_TOOL_PLANNER=true
USE_PRODUCT_VALIDATION=true
ENABLE_OBSERVABILITY=true

# 🔵 OPTIONAL (для Celery)
# CELERY_ENABLED=true
# REDIS_URL (Railway Redis add-on)
```

### Після деплою

1. **Отримай URL**: `https://xxx.up.railway.app`
2. **Онови PUBLIC_BASE_URL** в Railway Variables
3. **Перевір health**: `GET https://xxx.up.railway.app/health`
4. **Telegram webhook** зареєструється автоматично

### Railway + Redis (для Workers)

```bash
# 1. Railway Dashboard → Add Service → Redis
# 2. Railway автоматично встановить REDIS_URL
# 3. Додай в Variables:
CELERY_ENABLED=true

# 4. Додай другий сервіс для Worker:
# Start Command: celery -A src.workers.celery_app worker --loglevel=info
```

---

## Production Stack

```
┌─────────────────────────────────────────────────────┐
│                    Load Balancer                     │
│                  (nginx / Cloudflare)                │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│                   FastAPI App                        │
│               (uvicorn, 2+ replicas)                 │
│                  Port: 8000                          │
└─────────────────────────┬───────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────────┐
│   Redis     │  │   Celery    │  │   Celery Beat   │
│   :6379     │  │   Workers   │  │   (scheduler)   │
│             │  │   (4x)      │  │                 │
└─────────────┘  └─────────────┘  └─────────────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │    Supabase     │
                 │   (PostgreSQL)  │
                 └─────────────────┘
```

## Docker Compose (Recommended)

### Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/your-org/mirt-ai.git
cd mirt-ai
cp .env.example .env
# Edit .env with your API keys

# 2. Start all services
docker-compose up -d

# 3. Verify
curl http://localhost:8000/health
```

### Services

| Service         | Port | Command                   |
| --------------- | ---- | ------------------------- |
| `app`           | 8000 | FastAPI webhook server    |
| `redis`         | 6379 | Celery broker             |
| `celery-worker` | -    | Background task processor |
| `celery-beat`   | -    | Periodic task scheduler   |
| `flower`        | 5555 | Monitoring UI (optional)  |

### Enable Celery Workers

```bash
# Start core services
docker-compose up -d app redis celery-worker celery-beat

# Add monitoring (optional)
docker-compose --profile monitoring up -d
```

### Scaling Workers

```bash
# Scale to 3 workers
docker-compose up -d --scale celery-worker=3
```

## Manual Deployment

### Prerequisites

- Python 3.11+
- Redis 7+
- PostgreSQL (via Supabase)

### 1. Install Dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env:
# - REDIS_URL=redis://your-redis-host:6379/0
# - CELERY_ENABLED=true
# - All API keys
```

### 3. Start Services

```bash
# Terminal 1: FastAPI
uvicorn src.server.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Celery Worker
celery -A src.workers.celery_app worker \
  --loglevel=INFO \
  --concurrency=4 \
  --queues=default,llm,summarization,followups,crm,webhooks

# Terminal 3: Celery Beat
celery -A src.workers.celery_app beat --loglevel=INFO
```

## Systemd Services

### `/etc/systemd/system/mirt-api.service`

```ini
[Unit]
Description=MIRT AI API
After=network.target

[Service]
Type=simple
User=mirt
WorkingDirectory=/opt/mirt-ai
Environment="PATH=/opt/mirt-ai/.venv/bin"
EnvironmentFile=/opt/mirt-ai/.env
ExecStart=/opt/mirt-ai/.venv/bin/uvicorn src.server.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `/etc/systemd/system/mirt-celery.service`

```ini
[Unit]
Description=MIRT AI Celery Worker
After=network.target redis.service

[Service]
Type=simple
User=mirt
WorkingDirectory=/opt/mirt-ai
Environment="PATH=/opt/mirt-ai/.venv/bin"
EnvironmentFile=/opt/mirt-ai/.env
ExecStart=/opt/mirt-ai/.venv/bin/celery -A src.workers.celery_app worker --loglevel=INFO --concurrency=4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `/etc/systemd/system/mirt-beat.service`

```ini
[Unit]
Description=MIRT AI Celery Beat
After=network.target redis.service

[Service]
Type=simple
User=mirt
WorkingDirectory=/opt/mirt-ai
Environment="PATH=/opt/mirt-ai/.venv/bin"
EnvironmentFile=/opt/mirt-ai/.env
ExecStart=/opt/mirt-ai/.venv/bin/celery -A src.workers.celery_app beat --loglevel=INFO
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Enable Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable mirt-api mirt-celery mirt-beat
sudo systemctl start mirt-api mirt-celery mirt-beat
```

## Environment Variables

### Required

| Variable             | Description                |
| -------------------- | -------------------------- |
| `OPENROUTER_API_KEY` | OpenRouter API key for LLM |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token         |
| `SUPABASE_URL`       | Supabase project URL       |
| `SUPABASE_API_KEY`   | Supabase service role key  |

### Celery (Production)

| Variable                     | Default                    | Description                 |
| ---------------------------- | -------------------------- | --------------------------- |
| `REDIS_URL`                  | `redis://localhost:6379/0` | Redis connection URL        |
| `CELERY_ENABLED`             | `false`                    | Enable Celery workers       |
| `CELERY_CONCURRENCY`         | `4`                        | Worker processes            |
| `CELERY_MAX_TASKS_PER_CHILD` | `100`                      | Tasks before worker restart |

### Monitoring

| Variable             | Description                            |
| -------------------- | -------------------------------------- |
| `SENTRY_DSN`         | Sentry error tracking DSN              |
| `SENTRY_ENVIRONMENT` | `production`, `staging`, `development` |
| `FLOWER_AUTH`        | Flower UI credentials (`user:pass`)    |

## Health Checks

### API Health

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "ok",
  "checks": {
    "supabase": "ok",
    "redis": "ok",
    "celery_workers": {"status": "ok", "count": 4}
  },
  "celery_enabled": true
}
```

### Celery Health

```bash
# Ping workers
celery -A src.workers.celery_app inspect ping

# Active tasks
celery -A src.workers.celery_app inspect active

# Queue lengths
celery -A src.workers.celery_app inspect stats
```

## Monitoring

### Flower UI

```bash
# Docker
docker-compose --profile monitoring up -d
# Access: http://localhost:5555

# Manual
celery -A src.workers.celery_app flower --port=5555
```

### Sentry Integration

Set `SENTRY_DSN` in `.env` to enable:
- Error tracking
- Performance monitoring
- Celery task tracking

## Troubleshooting

### Workers Not Starting

```bash
# Check Redis connection
redis-cli ping

# Check Celery app loads
python -c "from src.workers.celery_app import celery_app; print(celery_app)"
```

### Tasks Not Processing

```bash
# Check worker is listening to queues
celery -A src.workers.celery_app inspect active_queues

# Check task registered
celery -A src.workers.celery_app inspect registered
```

### Memory Issues

```bash
# Reduce concurrency
CELERY_CONCURRENCY=2

# Lower max tasks per child
CELERY_MAX_TASKS_PER_CHILD=50
```
