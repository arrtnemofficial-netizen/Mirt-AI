# Celery

## Увімкнення

- `CELERY_ENABLED=true`
- `MANYCHAT_USE_CELERY=true` — ManyChat повідомлення обробляються воркером.

## Запуск локально

```bash
celery -A src.workers.celery_app worker -l info
celery -A src.workers.celery_app beat -l info
```

## Корисні налаштування

- `CELERY_CONCURRENCY`
- `CELERY_MAX_TASKS_PER_CHILD`
- `CELERY_RESULT_TIMEOUT`

## Навіщо потрібен beat

Beat запускає періодичні задачі (follow-up, cleanup).
