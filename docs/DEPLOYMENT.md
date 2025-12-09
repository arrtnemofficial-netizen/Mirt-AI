# Deployment Guide

> 📚 **Центральний індекс:** [../DOCUMENTATION.md](../DOCUMENTATION.md)

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Supabase Account (or local Postgres)
- OpenRouter API Key

### Local Development

1. **Setup Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. **Install Dependencies**
   ```bash
   make setup
   ```

3. **Run Server**
   ```bash
   # Starts FastAPI on port 8000
   python src/run.py
   ```

4. **Run Workers (Optional)**
   ```bash
   # Starts Celery worker
   python scripts/run_worker.py
   ```

---

## 🐳 Docker Deployment

We use a multi-stage Dockerfile for minimal production images.

### Build & Run
```bash
docker-compose up -d --build
```

This starts:
- `app`: FastAPI server (Port 8000)
- `worker`: Celery worker
- `redis`: Message broker

---

## 🚂 Railway Deployment

The project is configured for one-click deployment on [Railway](https://railway.app).

- **Config**: `railway.toml` handles build and deploy settings.
- **Entrypoint**: `python src/run.py` (automatically picks up `$PORT`).
- **Build**: Uses `nixpacks` or `Dockerfile` (configured in `railway.toml`).

### Environment Variables
Ensure these are set in Railway dashboard:
- `OPENROUTER_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_API_KEY`
- `TELEGRAM_BOT_TOKEN` (if using Telegram)
- `PUBLIC_BASE_URL` (Your Railway URL)

---

## 🔄 Webhooks

### Telegram
Set the webhook automatically on startup by configuring:
`PUBLIC_BASE_URL=https://your-app.up.railway.app`

### ManyChat
Point your ManyChat "External Request" to:
`https://your-app.up.railway.app/webhooks/manychat`

Headers:
- `X-ManyChat-Token`: (Your configured secret)
