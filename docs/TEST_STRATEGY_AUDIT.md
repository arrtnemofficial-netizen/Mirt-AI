# Аудит тест-стратегії

## Пробіли

- `src/integrations/manychat/` — потрібні unit/інтеграційні тести, особливо pipeline tests.
- `LangGraph` — відсутні тести на станові переходи.
- `Persistence` — chaos/інтеграційні тести для надійності.

## Рекомендації

- Retry/backoff для ManyChat push API (написати unit-тести).
- Додати pooler timeout для стабільності.

