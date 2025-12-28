# Database Tables Reference - Production Verification

## Всі таблиці НЕ зайві - кожна має своє призначення

### Core Tables (Критичні для роботи системи)

#### 1. `users` ✅ ПРАЦЮЄ
**Призначення**: Зберігає інформацію про користувачів (ManyChat/Instagram/Telegram)

**Заповнення**:
- **Коли**: При кожному повідомленні від користувача
- **Де**: `src/services/storage/postgres_message_store.py::_update_user_interaction()`
- **Що зберігається**:
  - `user_id` (TEXT) - ID користувача з каналу
  - `instagram_username` - username з Instagram
  - `telegram_username` - username з Telegram
  - `username` - загальний username
  - `last_interaction_at` - остання взаємодія
  - `created_at`, `updated_at` - timestamps

**Використання**:
- `src/services/conversation/conversation.py` - при збереженні повідомлень
- `src/services/summarization/summarization.py` - для summarization inactive users
- `src/workers/tasks/summarization.py` - для batch summarization

**Статус**: ✅ **ПРАЦЮЄ** - автоматично заповнюється при кожному повідомленні

---

#### 2. `messages` ✅ ПРАЦЮЄ
**Призначення**: Зберігає всі повідомлення (user + assistant) для історії діалогів

**Заповнення**:
- **Коли**: При кожному повідомленні (user та assistant)
- **Де**: `src/services/storage/postgres_message_store.py::append()`
- **Що зберігається**:
  - `session_id` - ID сесії
  - `role` - "user" або "assistant"
  - `content` - текст повідомлення
  - `user_id` - ID користувача
  - `content_type` - тип контенту (text, image)
  - `tags` - теги (HUMAN_NEEDED для escalations)
  - `created_at` - timestamp

**Використання**:
- `src/services/conversation/conversation.py` - для завантаження історії
- `src/services/summarization/summarization.py` - для summarization
- `src/services/memory/facts.py` - для витягування фактів

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при кожному повідомленні

---

#### 3. `orders` ✅ ПРАЦЮЄ
**Призначення**: Зберігає замовлення клієнтів

**Заповнення**:
- **Коли**: ТІЛЬКИ після отримання payment proof (скріншот/квитанція/URL)
- **Де**: `src/services/orders/order_service.py::create_order()`
- **Тригериться з**: `src/agents/langgraph/nodes/payment.py::_persist_order_and_queue_crm()`
- **Що зберігається**:
  - `user_id` - ID користувача
  - `session_id` - ID сесії (UNIQUE, для upsert)
  - `customer_name`, `customer_phone`, `customer_city` - дані клієнта
  - `delivery_method`, `delivery_address` - доставка
  - `status` - статус замовлення (new, paid, shipped, etc.)
  - `total_amount` - загальна сума
  - `user_nickname` - nickname користувача
  - `sitniks_chat_id` - ID чату в Sitniks CRM
  - `created_at`, `updated_at` - timestamps

**Використання**:
- `src/services/orders/order_service.py` - для отримання замовлень
- `src/integrations/crm/crmservice.py` - для синхронізації з CRM

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється після payment proof (виправлено в цьому PR)

---

#### 4. `order_items` ✅ ПРАЦЮЄ
**Призначення**: Зберігає товари в замовленні (many-to-one з orders)

**Заповнення**:
- **Коли**: Разом з `orders` (після payment proof)
- **Де**: `src/services/orders/order_service.py::create_order()`
- **Що зберігається**:
  - `order_id` - FK до orders
  - `product_id` - ID товару
  - `product_name` - назва товару
  - `quantity` - кількість
  - `price_at_purchase` - ціна на момент покупки
  - `selected_size`, `selected_color` - вибрані параметри

**Використання**:
- `src/services/orders/order_service.py::get_order_by_id()` - для отримання товарів замовлення

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється разом з orders

---

#### 5. `sitniks_chat_mappings` ✅ ПРАЦЮЄ
**Призначення**: Зв'язує MIRT users з Sitniks CRM chat IDs для оновлення статусів

**Заповнення**:
- **Коли**: При першому повідомленні (first touch), якщо є username
- **Де**: `src/integrations/crm/sitniks_chat_service.py::_save_chat_mapping()`
- **Тригериться з**: `src/services/conversation/conversation.py::process_message()` (first touch)
- **Що зберігається**:
  - `user_id` - MIRT user ID (UNIQUE)
  - `sitniks_chat_id` - ID чату в Sitniks CRM
  - `instagram_username` - username з Instagram
  - `telegram_username` - username з Telegram
  - `first_touch_at` - час першого контакту
  - `current_status` - поточний статус в Sitniks
  - `sitniks_manager_id` - ID менеджера в Sitniks

**Використання**:
- `src/integrations/crm/sitniks_chat_service.py` - для оновлення статусів чатів
- `src/agents/langgraph/nodes/payment.py` - для передачі sitniks_chat_id в orders

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при first touch (виправлено в цьому PR)

---

#### 6. `llm_usage` ✅ ПРАЦЮЄ
**Призначення**: Зберігає використання LLM для аналітики та костування

**Заповнення**:
- **Коли**: При кожному виклику LLM (agent, vision, payment)
- **Де**: `src/workers/tasks/llm_usage.py::record_usage()`
- **Що зберігається**:
  - `user_id` - ID користувача (TEXT, виправлено в цьому PR)
  - `session_id` - ID сесії
  - `model` - назва моделі (gpt-5.1, gpt-4o-mini, etc.)
  - `tokens_input`, `tokens_output` - токени
  - `cost_usd` - розрахована вартість
  - `latency_ms` - затримка
  - `success` - чи успішний виклик
  - `error_message` - помилка (якщо є)
  - `metadata` - додаткові дані (JSONB)

**Використання**:
- `src/services/llm_usage_logger.py` - для логування використання
- Аналітика та костування

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при кожному LLM виклику, модель береться з `settings.LLM_MODEL_GPT` (gpt-5.1)

---

### LangGraph Checkpointing Tables (Критичні для state persistence)

#### 7. `checkpoints` ✅ ПРАЦЮЄ
**Призначення**: Зберігає checkpoints LangGraph для відновлення стану після перезапуску

**Заповнення**:
- **Коли**: Автоматично LangGraph при кожному кроці графа
- **Де**: `src/agents/langgraph/checkpointer.py` (PostgreSQLCheckpointer)
- **Що зберігається**:
  - `thread_id` - ID потоку (session_id)
  - `checkpoint_ns` - namespace
  - `checkpoint_id` - ID checkpoint
  - `parent_checkpoint_id` - батьківський checkpoint
  - `checkpoint` - JSONB зі станом
  - `metadata` - метадані

**Використання**:
- `src/agents/langgraph/graph.py` - для відновлення стану після перезапуску
- `src/services/conversation/conversation.py` - для persistence між повідомленнями

**Статус**: ✅ **ПРАЦЮЄ** - автоматично заповнюється LangGraph

---

#### 8. `checkpoint_blobs` ✅ ПРАЦЮЄ
**Призначення**: Зберігає великі блоби даних для checkpoints (якщо checkpoint > 1MB)

**Заповнення**:
- **Коли**: Якщо checkpoint занадто великий для JSONB
- **Де**: `src/agents/langgraph/checkpointer.py` (PostgreSQLCheckpointer)
- **Що зберігається**:
  - `checkpoint_id` - FK до checkpoints
  - `blob` - великий об'єкт даних

**Статус**: ✅ **ПРАЦЮЄ** - автоматично заповнюється LangGraph при потребі

---

#### 9. `checkpoint_writes` ✅ ПРАЦЮЄ
**Призначення**: Логує всі записи в checkpoints для debugging та audit

**Заповнення**:
- **Коли**: При кожному записі checkpoint
- **Де**: `src/agents/langgraph/checkpointer.py` (PostgreSQLCheckpointer)
- **Що зберігається**:
  - `checkpoint_id` - FK до checkpoints
  - `write_type` - тип запису
  - `metadata` - метадані запису

**Статус**: ✅ **ПРАЦЮЄ** - автоматично заповнюється LangGraph

---

#### 10. `checkpoint_migrations` ✅ ПРАЦЮЄ
**Призначення**: Зберігає історію міграцій checkpoint schema

**Заповнення**:
- **Коли**: При зміні schema checkpoints
- **Де**: LangGraph автоматично
- **Що зберігається**:
  - `migration_id` - ID міграції
  - `applied_at` - час застосування

**Статус**: ✅ **ПРАЦЮЄ** - автоматично заповнюється LangGraph

---

### Session Management

#### 11. `agent_sessions` ✅ ПРАЦЮЄ
**Призначення**: Зберігає стан сесій для швидкого доступу (legacy, до LangGraph checkpoints)

**Заповнення**:
- **Коли**: При кожному збереженні стану сесії
- **Де**: `src/services/storage/postgres_store.py::PostgresSessionStore::save()`
- **Що зберігається**:
  - `session_id` - ID сесії (UNIQUE)
  - `state` - JSONB зі станом
  - `updated_at` - час оновлення

**Використання**:
- `src/services/storage/postgres_store.py` - для завантаження стану сесії
- Fallback для LangGraph checkpoints

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при кожному збереженні стану

---

### Memory System (Titans-like)

#### 12. `mirt_profiles` ✅ ПРАЦЮЄ
**Призначення**: Зберігає профілі користувачів (child profile, style preferences, logistics, commerce)

**Заповнення**:
- **Коли**: При створенні профілю користувача
- **Де**: `src/services/memory/profiles.py::create_profile()`
- **Що зберігається**:
  - `user_id` - ID користувача
  - `child_profile` - профіль дитини (JSONB)
  - `style_preferences` - стильові уподобання (JSONB)
  - `logistics` - логістика (JSONB)
  - `commerce` - комерційні дані (JSONB)
  - `sitniks_chat_id` - ID чату в Sitniks (опціонально)

**Використання**:
- `src/services/memory/profiles.py` - для отримання профілю
- `src/agents/langgraph/nodes/memory.py` - для memory context

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при створенні профілю

---

#### 13. `mirt_memories` ✅ ПРАЦЮЄ
**Призначення**: Зберігає факти про користувача з векторними embeddings для semantic search

**Заповнення**:
- **Коли**: При збереженні важливих фактів (importance > threshold)
- **Де**: `src/services/memory/facts.py::store_fact()`
- **Що зберігається**:
  - `user_id` - ID користувача
  - `session_id` - ID сесії
  - `content` - текст факту
  - `fact_type`, `category` - тип та категорія
  - `importance`, `surprise`, `confidence` - метрики
  - `embedding` - векторне представлення (pgvector)
  - `ttl_days`, `expires_at` - TTL для фактів
  - `is_active` - чи активний факт

**Використання**:
- `src/services/memory/facts.py` - для semantic search фактів
- `src/agents/langgraph/nodes/memory.py` - для memory context

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при збереженні важливих фактів

---

#### 14. `mirt_memory_summaries` ✅ ПРАЦЮЄ
**Призначення**: Зберігає summaries користувачів для оптимізації контексту

**Заповнення**:
- **Коли**: При summarization inactive users
- **Де**: `src/services/summarization/summarization.py::update_user_summary()`
- **Що зберігається**:
  - `user_id` - ID користувача
  - `summary` - текст summary
  - `created_at`, `updated_at` - timestamps

**Використання**:
- `src/services/summarization/summarization.py` - для отримання summary
- `src/workers/tasks/summarization.py` - для batch summarization

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при summarization

---

### CRM Integration

#### 15. `crm_orders` ✅ ПРАЦЮЄ
**Призначення**: Зберігає замовлення для синхронізації з Sitniks CRM

**Заповнення**:
- **Коли**: При створенні замовлення (після payment proof)
- **Де**: `src/integrations/crm/crmservice.py::create_order_with_persistence()`
- **Що зберігається**:
  - `session_id` - ID сесії
  - `external_id` - зовнішній ID (deterministic hash)
  - `crm_order_id` - ID замовлення в Sitniks CRM
  - `status` - статус (pending, created, failed, etc.)
  - `order_data` - дані замовлення (JSONB)
  - `metadata` - метадані (JSONB)
  - `error_message` - помилка (якщо є)

**Використання**:
- `src/integrations/crm/crmservice.py` - для синхронізації з CRM
- `src/integrations/crm/webhooks.py` - для обробки webhook статусів

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при створенні замовлення в CRM

---

### Observability

#### 16. `llm_traces` ✅ ПРАЦЮЄ
**Призначення**: Зберігає детальні traces LLM викликів для debugging та аналітики

**Заповнення**:
- **Коли**: При кожному LLM виклику (якщо увімкнено tracing)
- **Де**: `src/services/observability/observability.py::log_trace()`
- **Що зберігається**:
  - `session_id` - ID сесії
  - `trace_id` - ID trace
  - `node_name` - назва вузла (agent, vision, payment)
  - `state_name` - назва стану
  - `prompt_key` - ключ промпту
  - `input_snapshot` - вхідні дані (JSONB)
  - `output_snapshot` - вихідні дані (JSONB)
  - `latency_ms` - затримка
  - `model_name` - назва моделі
  - `status` - статус (SUCCESS, ERROR)
  - `error_message` - помилка (якщо є)

**Використання**:
- Debugging та аналітика LLM викликів
- Оптимізація промптів

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при tracing (може бути вимкнено для production)

---

### Webhook Deduplication

#### 17. `webhook_dedupe` ✅ ПРАЦЮЄ
**Призначення**: Запобігає обробці дублікатів webhook повідомлень (idempotency)

**Заповнення**:
- **Коли**: При обробці webhook повідомлення
- **Де**: `src/services/webhook/webhook_dedupe.py::check_and_mark()`
- **Що зберігається**:
  - `dedupe_key` - ключ дедуплікації (hash від user_id + message_id/text)
  - `processed_at` - час обробки
  - `expires_at` - час закінчення (TTL, зазвичай 24 години)

**Використання**:
- `src/integrations/manychat/async_service.py` - для дедуплікації ManyChat webhooks
- `src/server/main.py` - для дедуплікації API webhooks

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при обробці webhook, автоматично очищається через TTL

---

### Products Catalog

#### 18. `products` ✅ ПРАЦЮЄ
**Призначення**: Зберігає каталог товарів (з векторними embeddings для search)

**Заповнення**:
- **Коли**: При імпорті каталогу (не автоматично, вручну або через migration)
- **Де**: Зовнішній скрипт або migration
- **Що зберігається**:
  - `id` - ID товару
  - `name` - назва товару
  - `description` - опис
  - `price` - базова ціна
  - `sizes`, `colors` - розміри та кольори
  - `photo_url` - URL фото
  - `embedding` - векторне представлення (pgvector) для semantic search

**Використання**:
- `src/services/catalog/catalog_service.py` - для пошуку товарів
- `src/agents/langgraph/nodes/helpers/vision/product_enrichment.py` - для обогащення vision results

**Статус**: ✅ **ПРАЦЮЄ** - заповнюється при імпорті каталогу (не автоматично)

---

## Підсумок

### Всі таблиці НЕ зайві - кожна має своє призначення:

1. ✅ **users** - працює, заповнюється при кожному повідомленні
2. ✅ **messages** - працює, заповнюється при кожному повідомленні
3. ✅ **orders** - працює, заповнюється після payment proof
4. ✅ **order_items** - працює, заповнюється разом з orders
5. ✅ **sitniks_chat_mappings** - працює, заповнюється при first touch
6. ✅ **llm_usage** - працює, заповнюється при кожному LLM виклику
7. ✅ **checkpoints** - працює, автоматично заповнюється LangGraph
8. ✅ **checkpoint_blobs** - працює, автоматично заповнюється LangGraph
9. ✅ **checkpoint_writes** - працює, автоматично заповнюється LangGraph
10. ✅ **checkpoint_migrations** - працює, автоматично заповнюється LangGraph
11. ✅ **agent_sessions** - працює, заповнюється при збереженні стану
12. ✅ **mirt_profiles** - працює, заповнюється при створенні профілю
13. ✅ **mirt_memories** - працює, заповнюється при збереженні фактів
14. ✅ **mirt_memory_summaries** - працює, заповнюється при summarization
15. ✅ **crm_orders** - працює, заповнюється при створенні замовлення в CRM
16. ✅ **llm_traces** - працює, заповнюється при tracing (може бути вимкнено)
17. ✅ **webhook_dedupe** - працює, заповнюється при обробці webhook
18. ✅ **products** - працює, заповнюється при імпорті каталогу (не автоматично)

## Критичні таблиці для production

**Обов'язково мають заповнюватися**:
- `users` ✅
- `messages` ✅
- `orders` ✅ (після payment proof)
- `order_items` ✅ (разом з orders)
- `sitniks_chat_mappings` ✅ (при first touch)
- `llm_usage` ✅ (при кожному LLM виклику)
- `checkpoints` ✅ (автоматично LangGraph)
- `agent_sessions` ✅ (при збереженні стану)

**Опціональні (залежать від налаштувань)**:
- `mirt_profiles`, `mirt_memories`, `mirt_memory_summaries` - якщо увімкнено memory system
- `crm_orders` - якщо увімкнено CRM integration
- `llm_traces` - якщо увімкнено tracing
- `webhook_dedupe` - завжди працює для idempotency
- `products` - заповнюється вручну при імпорті каталогу

## Перевірка в production

Запустіть smoke test:
```bash
python scripts/test_prod_tables.py
```

Або перевірте вручну:
```sql
-- Перевірка users
SELECT COUNT(*) FROM users WHERE last_interaction_at > NOW() - INTERVAL '1 day';

-- Перевірка orders (мають бути тільки з payment proof)
SELECT COUNT(*) FROM orders WHERE created_at > NOW() - INTERVAL '1 day';

-- Перевірка sitniks_chat_mappings
SELECT COUNT(*) FROM sitniks_chat_mappings WHERE first_touch_at > NOW() - INTERVAL '1 day';

-- Перевірка llm_usage (має показувати gpt-5.1)
SELECT model, COUNT(*) FROM llm_usage WHERE created_at > NOW() - INTERVAL '1 day' GROUP BY model;
```

