# ManyChat Push Mode (Async)

## Режими

| Режим | Опис | Вимоги |
|---|---|---|
| Push | Обробка до 30s timeout | Потрібен API key |
| Response | Синхронний | Немає timeout |

## Архітектура потоку

Debounce + handler об'єднані для push/response:
- `src/integrations/manychat/pipeline.py`

## Змінні середовища

```env
MANYCHAT_API_KEY=...
MANYCHAT_API_URL=https://api.manychat.com
MANYCHAT_VERIFY_TOKEN=...
MANYCHAT_PUSH_MODE=true
```

## Таймаути для push

Обробка зображення може тривати до 30 секунд (Vision, обробка LLM).

