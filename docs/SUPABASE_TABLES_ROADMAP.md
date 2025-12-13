# 📊 MIRT AI - Supabase Tables Roadmap

> Повний опис всіх таблиць в Supabase, їх призначення, структура та використання в коді.

---

## 🗂️ Зміст

1. [Core Tables](#1-core-tables) - Основні таблиці системи
2. [Memory System](#2-memory-system-titans-like) - AGI-стиль памʼять
3. [LangGraph Checkpointing](#3-langgraph-checkpointing) - Збереження стану графа
4. [CRM Integration](#4-crm-integration) - Інтеграція з Sitniks CRM
5. [Observability](#5-observability) - Моніторинг та метрики
6. [E-Commerce](#6-e-commerce) - Замовлення та товари
7. [Quick Reference](#7-quick-reference) - Швидка довідка

---

## 1. Core Tables

### 📋 `agent_sessions`

**Призначення**: Зберігання стану розмови для кожної сесії.

| Поле | Тип | Опис |
|------|-----|------|
| `session_id` | TEXT PRIMARY KEY | Telegram/ManyChat ID |
| `state` | JSONB | Повний стан розмови (LangGraph state) |
| `created_at` | TIMESTAMPTZ | Коли створено |
| `updated_at` | TIMESTAMPTZ | Коли оновлено |

**Де використовується**:
- `src/services/supabase_store.py` - SupabaseSessionStore
- `src/workers/tasks/crm.py` - оновлення статусу замовлення

**Приклад state**:
```json
{
  "current_state": "STATE_4_OFFER",
  "dialog_phase": "OFFER_MADE",
  "messages": [...],
  "selected_products": [...],
  "metadata": {
    "session_id": "5863750352",
    "customer_name": "Юрій Немченко",
    "customer_phone": "+380951392121"
  }
}
```

---

### 📋 `messages`

**Призначення**: Історія повідомлень для followups та аналітики.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BIGINT | Primary key |
| `session_id` | TEXT | ID сесії |
| `user_id` | TEXT | Зовнішній ID користувача |
| `role` | TEXT | user/assistant/system |
| `content` | TEXT | Текст повідомлення |
| `tags` | TEXT[] | Теги для фільтрації |
| `created_at` | TIMESTAMPTZ | Час |

**Де використовується**:
- `src/services/message_store.py` - збереження історії
- `src/workers/tasks/followups.py` - followup повідомлення
- `src/workers/tasks/summarization.py` - генерація summary

---

### 📋 `users`

**Призначення**: Базова інформація про користувачів.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BIGINT | Primary key |
| `external_id` | TEXT UNIQUE | Telegram/ManyChat ID |
| `username` | TEXT | Username |
| `first_name` | TEXT | Імʼя |
| `created_at` | TIMESTAMPTZ | Реєстрація |

**Де використовується**:
- Посилання з інших таблиць
- Аналітика користувачів

---

## 2. Memory System (Titans-like)

> 3-рівнева архітектура памʼяті в стилі AGI

### 📋 `mirt_profiles` — Persistent Memory

**Призначення**: Стабільні дані про користувача, які ніколи не забуваються.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BIGINT | Primary key |
| `user_id` | TEXT UNIQUE | Зовнішній ID |
| `child_profile` | JSONB | Дані про дитину |
| `style_preferences` | JSONB | Вподобання стилю |
| `logistics` | JSONB | Дані доставки |
| `commerce` | JSONB | Покупницька поведінка |
| `completeness_score` | FLOAT | 0-1, повнота профілю |
| `sitniks_chat_id` | TEXT | ID чату в Sitniks CRM |

**Структура `child_profile`**:
```json
{
  "name": "Марійка",
  "age": 7,
  "height_cm": 128,
  "gender": "дівчинка",
  "body_type": "стандартна"
}
```

**Структура `style_preferences`**:
```json
{
  "favorite_models": ["Лагуна", "Ритм"],
  "favorite_colors": ["рожевий", "блакитний"],
  "avoided_colors": ["чорний"]
}
```

**Де використовується**:
- `src/agents/langgraph/nodes/memory.py` - memory_context_node
- `src/services/memory_service.py` - CRUD операції

---

### 📋 `mirt_memories` — Fluid Memory

**Призначення**: Атомарні факти з importance/surprise gating.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | UUID | Primary key |
| `user_id` | TEXT | FK → mirt_profiles |
| `content` | TEXT | Сам факт |
| `fact_type` | TEXT | preference/constraint/logistics/behavior |
| `category` | TEXT | child/style/delivery/payment |
| `importance` | FLOAT | 0-1, вплив на рекомендації |
| `surprise` | FLOAT | 0-1, новизна інформації |
| `confidence` | FLOAT | 0-1, впевненість |
| `decay_rate` | FLOAT | Денне зниження importance |
| `embedding` | VECTOR(1536) | Для semantic search |
| `is_active` | BOOLEAN | Чи активний факт |

**Gating Rule**: Зберігаємо тільки якщо `importance >= 0.6 AND surprise >= 0.4`

**Приклади фактів**:
```
importance=1.0: "Дитина має алергію на синтетику"
importance=0.8: "Любить рожевий колір"
importance<0.6: ignored (привітання, загальні фрази)
```

**Де використовується**:
- `src/agents/pydantic/memory_agent.py` - класифікація фактів
- `src/services/memory_tasks.py` - time decay, cleanup

---

### 📋 `mirt_memory_summaries` — Compressed Memory

**Призначення**: Стислі summary для зменшення токенів в промпті.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BIGINT | Primary key |
| `user_id` | TEXT | FK → mirt_profiles |
| `summary_type` | TEXT | user/product/session |
| `summary_text` | TEXT | Стислий текст |
| `key_facts` | TEXT[] | Ключові факти |
| `facts_count` | INT | Скільки фактів узагальнено |
| `is_current` | BOOLEAN | Чи актуальний |

**Де використовується**:
- Генерується weekly для активних користувачів
- Замість 100 фактів → 2-3 блоки

---

## 3. LangGraph Checkpointing

> Автоматично створюються AsyncPostgresSaver

### 📋 `checkpoints`

**Призначення**: Основна таблиця стану LangGraph.

| Поле | Тип | Опис |
|------|-----|------|
| `thread_id` | TEXT | ID потоку (session:uuid) |
| `checkpoint_ns` | TEXT | Namespace |
| `checkpoint_id` | TEXT | ID чекпоінту |
| `parent_checkpoint_id` | TEXT | Батьківський чекпоінт |
| `type` | TEXT | Тип |
| `checkpoint` | JSONB | Серіалізований стан |
| `metadata` | JSONB | Метадані |

**RLS**: UNRESTRICTED (LangGraph потребує прямого доступу)

---

### 📋 `checkpoint_blobs`

**Призначення**: Великі бінарні дані чекпоінтів.

---

### 📋 `checkpoint_writes`

**Призначення**: Запис змін чекпоінтів.

---

### 📋 `checkpoint_migrations`

**Призначення**: Версіонування схеми чекпоінтів.

**Де використовується**:
- `src/agents/langgraph/checkpointer.py` - AsyncPostgresSaver

---

## 4. CRM Integration

### 📋 `crm_orders`

**Призначення**: Mapping між сесіями та замовленнями в Sitniks CRM.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | UUID | Primary key |
| `session_id` | TEXT | ID сесії |
| `external_id` | TEXT UNIQUE | Унікальний ID (session_timestamp) |
| `crm_order_id` | TEXT | ID в Sitniks CRM |
| `status` | TEXT | pending/queued/created/processing/shipped/delivered/cancelled/failed |
| `order_data` | JSONB | Повні дані замовлення |
| `metadata` | JSONB | Дані з webhooks |
| `task_id` | TEXT | Celery task ID |
| `error_message` | TEXT | Помилка якщо failed |

**Де використовується**:
- `src/integrations/crm/crmservice.py` - CRMService
- `src/workers/tasks/crm.py` - async order operations

---

### 📋 `sitniks_chat_mappings`

**Призначення**: Звʼязок між MIRT users та Sitniks CRM chats.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | UUID | Primary key |
| `user_id` | TEXT | MIRT user ID |
| `instagram_username` | TEXT | Instagram username |
| `telegram_username` | TEXT | Telegram username |
| `sitniks_chat_id` | TEXT UNIQUE | ID чату в Sitniks |
| `sitniks_manager_id` | INTEGER | ID менеджера |
| `current_status` | TEXT | Поточний статус |
| `first_touch_at` | TIMESTAMPTZ | Перший контакт |

**Статуси в Sitniks**:
- "Взято в роботу" → перше повідомлення
- "Виставлено рахунок" → показано реквізити
- "AI Увага" → ескалація

**Де використовується**:
- `src/integrations/crm/sitniks_chat_service.py` - SitniksChatService

---

## 5. Observability

### 📋 `llm_traces`

**Призначення**: Детальні логи кожного LLM виклику.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | UUID | Primary key |
| `session_id` | TEXT | ID сесії |
| `trace_id` | UUID | ID логічного потоку |
| `node_name` | TEXT | agent_node/vision_node/etc |
| `state_name` | TEXT | STATE_4_OFFER/etc |
| `input_snapshot` | JSONB | Вхідні дані |
| `output_snapshot` | JSONB | Результат |
| `status` | ENUM | SUCCESS/ERROR/BLOCKED/ESCALATED |
| `error_category` | ENUM | SCHEMA/BUSINESS/SAFETY/SYSTEM |
| `latency_ms` | FLOAT | Час виконання |
| `tokens_in` | INT | Вхідні токени |
| `tokens_out` | INT | Вихідні токени |
| `cost` | FLOAT | Вартість |
| `model_name` | TEXT | gpt-4o/grok-beta |

**RLS**: UNRESTRICTED

**Де використовується**:
- `src/services/observability.py` - log_trace()

---

### 📋 `llm_usage`

**Призначення**: Агреговане використання LLM для біллінгу.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BIGINT | Primary key |
| `user_id` | BIGINT | ID користувача |
| `model` | VARCHAR | Модель |
| `tokens_in` | INT | Вхідні токени |
| `tokens_out` | INT | Вихідні токени |
| `cost` | FLOAT | Вартість |
| `created_at` | TIMESTAMPTZ | Час |

**Де використовується**:
- `src/workers/tasks/llm_usage.py` - track_llm_usage()

---

## 6. E-Commerce

### 📋 `products`

**Призначення**: Каталог товарів.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BIGINT | Primary key |
| `name` | TEXT | Назва товару |
| `description` | TEXT | Опис |
| `category` | TEXT | Категорія |
| `subcategory` | TEXT | Підкатегорія |
| `price` | NUMERIC(10,2) | Ціна |
| `sizes` | TEXT[] | Доступні розміри |
| `colors` | TEXT[] | Доступні кольори |
| `photo_url` | TEXT | URL фото |
| `sku` | TEXT UNIQUE | Артикул |
| `embedding` | VECTOR(1536) | Для semantic search |

**RLS**: Public read access (каталог відкритий)

**Де використовується**:
- `src/services/catalog_service.py` - CatalogService

---

### 📋 `orders`

**Призначення**: Замовлення.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BIGINT | Primary key |
| `user_id` | TEXT | ID користувача |
| `session_id` | TEXT | ID сесії |
| `customer_name` | TEXT | ПІБ |
| `customer_phone` | TEXT | Телефон |
| `customer_city` | TEXT | Місто |
| `delivery_method` | TEXT | Метод доставки |
| `delivery_address` | TEXT | Адреса/відділення НП |
| `status` | TEXT | new/paid/shipped/cancelled |
| `total_amount` | NUMERIC(10,2) | Сума |
| `sitniks_chat_id` | TEXT | ID чату в Sitniks |

**Де використовується**:
- `src/services/order_service.py` - OrderService

---

### 📋 `order_items`

**Призначення**: Товари в замовленні.

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BIGINT | Primary key |
| `order_id` | BIGINT | FK → orders |
| `product_id` | BIGINT | FK → products |
| `product_name` | TEXT | Snapshot назви |
| `quantity` | INT | Кількість |
| `price_at_purchase` | NUMERIC(10,2) | Snapshot ціни |
| `selected_size` | TEXT | Вибраний розмір |
| `selected_color` | TEXT | Вибраний колір |

**Де використовується**:
- `src/services/order_service.py` - OrderService

---

## 7. Quick Reference

### 📊 Таблиці та Статуси

| Таблиця | RLS | Кількість записів | Частота запитів |
|---------|-----|-------------------|-----------------|
| `agent_sessions` | ✅ | ~активні сесії | Кожне повідомлення |
| `checkpoints` | ❌ UNRESTRICTED | ~активні сесії × 10 | Кожне повідомлення |
| `products` | ✅ Public read | ~30-100 | Кожен пошук |
| `mirt_profiles` | ✅ | ~унікальні users | Старт сесії |
| `mirt_memories` | ✅ | ~users × 10-50 | Старт сесії |
| `llm_traces` | ❌ UNRESTRICTED | ~messages × nodes | Кожен LLM call |
| `crm_orders` | ✅ | ~замовлення | При оформленні |

### 🔧 SQL Migrations

```bash
# Порядок виконання міграцій
1. src/db/schema.sql           # products, orders, order_items
2. src/db/memory_schema.sql    # mirt_profiles, mirt_memories, mirt_memory_summaries
3. src/db/migrations/20241205_create_llm_traces.sql
4. src/integrations/crm/database_schema.sql  # crm_orders
5. src/integrations/crm/migrations/002_add_sitniks_chat_id.sql  # sitniks_chat_mappings
```

### ⚡ Важливі Extensions

```sql
-- Потрібні extensions
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector для embeddings
CREATE EXTENSION IF NOT EXISTS pg_cron;    -- Для scheduled tasks (optional)
```

### 🔐 Environment Variables

```bash
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_API_KEY=eyJhbG...            # service_role key
DATABASE_URL=postgresql://...          # Direct connection for LangGraph
```

---

## 📝 Примітки

1. **Checkpoints таблиці** створюються автоматично LangGraph AsyncPostgresSaver
2. **RLS UNRESTRICTED** для checkpoints і llm_traces - це нормально, бо service_role bypasses RLS
3. **pgvector** обовʼязковий для semantic search в products і mirt_memories
4. **Scheduled tasks** (memory decay, summarization) потребують Celery або pg_cron

---

*Документ створено: 2025-12-11*
*Версія: 1.0*
