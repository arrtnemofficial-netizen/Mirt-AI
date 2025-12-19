# Посібник для розробки

## Запуск локально

```bash
python -m uvicorn src.server.main:app --reload
```

## Форматування та лінтинг

```bash
python -m ruff format .
python -m ruff check .
```

## Тести

```bash
python -m pytest
```

## Тестування інтеграції ManyChat

1) Налаштуйте API ключ у `.env`.
2) Надішліть POST на `/api/v1/messages` або `/webhooks/manychat`.
3) Спостерігайте за подіями `manychat_debounce_aggregated`, `manychat_time_budget_exceeded`.

## Корисні поради

- Використовуйте `.env.example` як шаблон для змінних середовища.
- Переконайтеся, що Redis та Postgres доступні локально.
- Для дебагу використовуйте `DEBUG=true` у `.env`.

