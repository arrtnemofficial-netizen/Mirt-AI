# План покращень для production

## Що зроблено

- Рефакторинг сервісу ManyChat (debounce + handler)
- Trim policy для обмеження історії
- Оптимізація checkpointer
- Media URL валідація

## Наступні кроки

- Retry/backoff для ManyChat API
- Валідація env змінних у settings
- Моніторинг `manychat_time_budget_exceeded`

