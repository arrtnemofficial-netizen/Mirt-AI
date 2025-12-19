# Observability + Runbook (Production)

## Ключові сигнали

- `manychat_time_budget_exceeded`
  - Значення: запит перевищив ManyChat time budget.
  - Дії: перевірити checkpointer/LLM latency; подивитися `size_bytes` у логах.

- `manychat_debounce_aggregated`
  - Значення: debounce спрацював, повідомлення об’єднано.
  - Дії: дивимося delay, `final_text`.

- `manychat_debounce_superseded`
  - Значення: попереднє повідомлення замінено новим.
  - Дії: перевірити частоту інпутів/спам.

- `[CHECKPOINTER] aget_tuple/aput/aput_writes ... took ...`
  - Значення: повільний Postgres checkpointer.
  - Дії: перевірити pooler, state size, compaction.

- `[CHECKPOINTER] pool opened on demand`
  - Значення: пул відкривається під час запиту.
  - Дії: увімкнути warmup, відрегулювати pool sizes.

- `vision invalid_image_url` / `Timeout while downloading`
  - Значення: проблеми з CDN або завантаженням зображення.
  - Дії: media proxy, allowlist, повторити зображення.

- `state_messages_trimmed`
  - Значення: застосовано trim до state.
  - Дії: переглянути `STATE_MAX_MESSAGES` та політики.

## Рекомендовані ліміти

- `STATE_MAX_MESSAGES=100`
- `LLM_MAX_HISTORY_MESSAGES=20`
- `CHECKPOINTER_MAX_MESSAGES=200`
- `CHECKPOINTER_MAX_MESSAGE_CHARS=4000`
- `CHECKPOINTER_DROP_BASE64=true`

## Що робити при інциденті (швидкий чек-лист)
1) Перевірити логи `manychat_time_budget_exceeded` та `CHECKPOINTER aget_tuple/aput` (див. розмір payload).  
2) Якщо пул відкривається “on demand” → прогнати warmup або зменшити pool max_size.  
3) При проблемах із Vision CDN → увімкнути proxy/allowlist, перевірити `normalize_image_url`.  
4) Якщо trim спрацьовує часто → зменшити історію в промпті або підняти ліміти усвідомлено.  
5) За потреби тимчасово переводимо канал у спрощений режим (менше історії, більше fallback).
