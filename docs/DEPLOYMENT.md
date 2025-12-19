# Деплой (Railway)

## Сервіси

- Web (FastAPI)
- Worker (Celery)
- Beat (Celery beat)
- Redis (керований або окремий контейнер)

## Основні env

- `PUBLIC_BASE_URL` — повний HTTPS URL
- `OPENAI_API_KEY` / інші LLM ключі
- `DATABASE_URL` або `DATABASE_URL_POOLER`
- `SUPABASE_URL`, `SUPABASE_API_KEY`
- `REDIS_URL`
- `MANYCHAT_*`

## ManyChat режими

- `MANYCHAT_PUSH_MODE=true` — async push (202 + фонова обробка)
- `MANYCHAT_USE_CELERY=true` — використати Celery для push

## Production рекомендації

- Налаштувати `CHECKPOINTER_*` (pool/timeout/statement_timeout).
- Увімкнути media proxy для Vision (якщо CDN блокує).
- Заповнити `SITNIKS_HUMAN_MANAGER_ID` (int).

## Типові помилки

- Забутий `PUBLIC_BASE_URL` → https webhook не підтверджується.
- Некоректні типи в env → падіння pydantic settings (перевіряйте інти/булі).
