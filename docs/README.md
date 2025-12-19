# MIRT AI — асистент для бізнесу (UA)

MIRT AI — інтелектуальний асистент для обслуговування клієнтів. Підтримує ManyChat/Telegram, використовує LangGraph для ведення діалогу та зберігає сесії в Postgres/Supabase. Celery обробляє фонові задачі.

## Що робить система

- Приймає повідомлення з Instagram/Telegram.
- Обробляє запити з debounce для уникнення спаму.
- LangGraph веде діалог та зберігає контекст.
- ManyChat/Telegram надсилає відповіді користувачеві.

## Як запустити локально (dev)

1) Встановіть залежності:
```bash
python -m pip install -r requirements.txt
```

2) Налаштуйте змінні середовища:
- Див. `docs/DEPLOYMENT.md` та `.env.example`.

3) Запустіть API:
```bash
python -m uvicorn src.server.main:app --reload
```

4) (Опціонально) Запустіть worker/beat:
```bash
celery -A src.workers.celery_app worker -l info
celery -A src.workers.celery_app beat -l info
```

## Де читати далі

- Архітектура: `docs/ARCHITECTURE.md`
- ManyChat: `docs/MANYCHAT_PUSH_MODE.md`, `docs/MANYCHAT_SETUP.md`
- Деплой: `docs/DEPLOYMENT.md`
- Observability: `docs/OBSERVABILITY_RUNBOOK.md`

