# ADR: Vision Results Ledger (Idempotent Vision Layer)

## Context / Problem
- Vision pipeline зараз використовує лише Hash Guard (session_id + image_url) як швидкий захист від дублювання.
- Немає глобального `vision_result_id` і таблиці результатів → downstream (payment/CRM/notifications) не можуть перевірити, чи результат уже оброблено.
- Ризики: дублікати платежів/CRM-замовлень при повторних фотках, спам нотифікацій, неможливість аудиту.

## Decision
Запровадити Vision Results Ledger у Supabase/Postgres.
- Таблиця `vision_results` з унікальним `image_hash` та стабільним `vision_result_id` (UUID PK).
- `vision_node` вставляє/отримує запис за `image_hash` і повертає `vision_result_id` у metadata.
- Downstream (payment/CRM/notifications) використовують `vision_result_id` як ідемпотентний ключ; повторні запити з тим самим hash не дублюють дії.

## Schema (proposed)
```
vision_results (
  vision_result_id uuid primary key default gen_random_uuid(),
  session_id text not null,
  image_hash text not null unique,
  status text not null default 'processed',   -- processed | escalated | blocked | failed
  confidence numeric,
  identified_product jsonb,
  metadata jsonb,
  error_message text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
)
create unique index ux_vision_results_image_hash on vision_results(image_hash);
create index idx_vision_results_status on vision_results(status);
```

## Data Flow
1) vision_node: обчислює `image_hash` (session_id + image_url) → `insert ... on conflict (image_hash) do update set updated_at=now()` → отримує `vision_result_id`.
2) vision_node повертає `vision_result_id` у `agent_response.metadata`.
3) Payment/CRM/Notifications читають `vision_result_id` і перевіряють ledger перед діями; дублікати блокуються/ігноруються.

## Idempotency Rules
- `image_hash` унікальний: повторна фотка → той самий запис, статус не погіршуємо (крім fail → escalated/processed за бізнес-логікою).
- Downstream повинні зберігати/перевіряти `vision_result_id` (не створювати дубль, якщо status вже processed/escalated).

## Migration Plan
1) Додати SQL-міграцію `vision_results` (див. `scripts/db/migrations/0xx_add_vision_results.sql`).
2) Оновити vision_node для запису в ledger і прокидання `vision_result_id` в metadata.
3) Оновити payment/CRM/notification шари, щоб використовували `vision_result_id` як ідемпотентний ключ.
4) Додати тести: unit (hash guard + reuse existing result), integration (payment/CRM не дублюються при повторі).

## Alternatives
- Event bus (Kafka/Redis) з ack/idempotency — дорожче за інфраструктурою.
- Залишити тільки Hash Guard — не дає трасовності та глобального id.

## Status
Accepted. Реалізація: schema + code changes pending.
