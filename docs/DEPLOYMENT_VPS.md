# Деплой на VPS

## Системні вимоги

- Python 3.11+
- Redis
- Доступ до Postgres (local або managed)

## Покроково

1) Клонування репозиторію та віртуальне середовище.
2) Налаштування `.env` (див. `DEPLOYMENT.md`).
3) Створення systemd-сервісів для web (FastAPI) та Celery worker/beat.
4) Налаштування reverse proxy (nginx/caddy) та SSL.

## Моніторинг

- `/health` endpoint (простий healthcheck).
- Спостереження за подіями `manychat_debounce_aggregated`, `manychat_time_budget_exceeded`.

## Приклад systemd-юнітів

```ini
[Unit]
Description=MIRT Web
After=network.target

[Service]
User=mirt
WorkingDirectory=/opt/mirt
Environment=PATH=/opt/mirt/venv/bin
ExecStart=/opt/mirt/venv/bin/uvicorn src.server.main:app --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

Аналогічно для `celery worker` та `celery beat`.

