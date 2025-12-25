---
name: Supabase to PostgreSQL Migration
overview: "Повний перехід з Supabase на PostgreSQL (Railway): створення одного SQL скрипту для всіх таблиць, міграція даних, оновлення коду для використання прямого PostgreSQL замість Supabase client."
todos:
  - id: create_sql_script
    content: Створити scripts/sql/create_all_tables_postgresql.sql з усіма таблицями, extensions, triggers, functions, indexes
    status: pending
  - id: create_migration_script
    content: Створити scripts/migrate_data_from_supabase.py для міграції даних з Supabase в PostgreSQL
    status: pending
    dependencies:
      - create_sql_script
  - id: create_postgres_pool
    content: Створити src/services/postgres_pool.py для управління connection pool
    status: pending
  - id: create_postgres_store
    content: Створити src/services/postgres_store.py (PostgresSessionStore) замість SupabaseSessionStore
    status: pending
    dependencies:
      - create_postgres_pool
  - id: update_message_store
    content: Оновити src/services/message_store.py для використання PostgreSQL замість Supabase
    status: pending
    dependencies:
      - create_postgres_pool
  - id: update_webhook_dedupe
    content: Оновити src/services/webhook_dedupe.py для використання PostgreSQL
    status: pending
    dependencies:
      - create_postgres_pool
  - id: update_observability
    content: Оновити src/services/observability.py для логування llm_traces в PostgreSQL
    status: pending
    dependencies:
      - create_postgres_pool
  - id: update_workers
    content: Оновити всі workers (summarization, followups, llm_usage, crm) для використання PostgreSQL
    status: pending
    dependencies:
      - create_postgres_pool
  - id: update_config
    content: "Оновити src/conf/config.py: додати POSTGRES_* settings, оновити DATABASE_URL"
    status: pending
  - id: update_dependencies
    content: Оновити src/services/conversation.py та інші файли для використання PostgresSessionStore замість SupabaseSessionStore
    status: pending
    dependencies:
      - create_postgres_store
  - id: test_migration
    content: Створити тести для перевірки міграції та нового коду
    status: pending
    dependencies:
      - create_postgres_store
      - update_message_store
---

#Міграція з Supabase на PostgreSQL (Railway)

## Мета

Перехід з Supabase REST API на прямий PostgreSQL для всіх операцій БД, зберігаючи всі дані та функціональність.

## Етапи міграції

### 1. Створення SQL скрипту для всіх таблиць

**Файл:** `scripts/sql/create_all_tables_postgresql.sql`Скрипт має включати:

- Extensions: `vector` (pgvector), `pg_cron` (optional)
- Всі таблиці з `full_schema_sync.sql`:
- `products` (з VECTOR embedding)
- `orders` (з user_nickname, sitniks_chat_id)
- `order_items`
- `crm_orders`
- `sitniks_chat_mappings`
- `mirt_profiles` (з sitniks_chat_id)
- `mirt_memories` (з VECTOR embedding)
- `mirt_memory_summaries`
- `users` (з telegram_username, instagram_username)
- `messages`
- `llm_usage`
- `llm_traces` (з ENUMs)
- `agent_sessions` (з sitniks_chat_id)
- `webhook_dedupe`
- LangGraph checkpoints таблиці (якщо потрібно створити вручну):
- `checkpoints`
- `checkpoint_blobs`
- `checkpoint_writes`
- `checkpoint_migrations`
- Triggers: `update_updated_at_column()` для всіх таблиць
- RLS policies: permissive для service_role
- Functions: `summarize_inactive_users()`, `cleanup_expired_webhook_dedupe()`
- Indexes: всі необхідні індекси

**Вимоги:**

- Скрипт має бути IDEMPOTENT (можна запускати багато разів)
- Використовувати `CREATE TABLE IF NOT EXISTS`
- Використовувати `DO $$ ... END $$` для додавання колонок якщо таблиця вже існує

### 2. Створення скрипту міграції даних

**Файл:** `scripts/migrate_data_from_supabase.py`Скрипт має:

- Підключитись до Supabase (через Supabase client)
- Підключитись до PostgreSQL Railway (через psycopg)
- Мігрувати дані з таблиць:

1. `agent_sessions` (критично!)
2. `messages` (критично!)
3. `users`
4. `products`
5. `orders` + `order_items`
6. `crm_orders`
7. `sitniks_chat_mappings`
8. `mirt_profiles`
9. `mirt_memories`
10. `mirt_memory_summaries`
11. `llm_usage`
12. `llm_traces`
13. `webhook_dedupe`

- Логувати прогрес міграції
- Підтримувати resume (якщо міграція перервалась)
- Валідувати дані після міграції

### 3. Оновлення коду для використання PostgreSQL

**Файли для оновлення:**

#### 3.1. `src/services/supabase_store.py` → `src/services/postgres_store.py`

- Замінити Supabase client на psycopg
- Реалізувати `PostgresSessionStore` з тими ж методами:
- `get(session_id)` - SELECT з `agent_sessions`
- `save(session_id, state)` - UPSERT в `agent_sessions`
- `delete(session_id)` - DELETE з `agent_sessions`
- Видалити fallback store (не потрібен для прямого PostgreSQL)
- Використовувати connection pool

#### 3.2. `src/services/message_store.py`

- Створити `PostgresMessageStore` замість `SupabaseMessageStore`
- Реалізувати методи через psycopg:
- `append(message)` - INSERT в `messages`
- `list(session_id)` - SELECT з `messages`
- `delete(session_id)` - DELETE з `messages`
- Оновити `create_message_store()` для використання PostgreSQL

#### 3.3. `src/services/webhook_dedupe.py`

- Оновити `WebhookDedupeStore` для використання PostgreSQL замість Supabase client
- Використовувати psycopg для операцій

#### 3.4. `src/services/observability.py`

- Оновити логування `llm_traces` для використання PostgreSQL

#### 3.5. `src/workers/tasks/*.py`

- Оновити всі workers для використання PostgreSQL:
- `summarization.py` - users, messages
- `followups.py` - messages
- `llm_usage.py` - llm_usage
- `crm.py` - crm_orders, agent_sessions

#### 3.6. `src/integrations/crm/*.py`

- Оновити CRM інтеграцію для використання PostgreSQL

#### 3.7. `src/conf/config.py`

- Додати `POSTGRES_URL` або використовувати `DATABASE_URL`
- Можливо видалити `SUPABASE_URL`, `SUPABASE_API_KEY` (якщо не потрібні)
- Залишити `SUPABASE_TABLE`, `SUPABASE_MESSAGES_TABLE` для backward compatibility (перейменувати в `POSTGRES_*`)

#### 3.8. `src/services/supabase_client.py`

- Можливо перейменувати в `postgres_client.py` або залишити для backward compatibility
- Створити `get_postgres_connection()` для connection pool

### 4. Створення connection pool manager

**Файл:** `src/services/postgres_pool.py`

- Singleton connection pool для PostgreSQL
- Використовувати `psycopg_pool.AsyncConnectionPool`
- Налаштування через `config.py`:
- `POSTGRES_POOL_MIN_SIZE`
- `POSTGRES_POOL_MAX_SIZE`
- `POSTGRES_POOL_MAX_IDLE`

### 5. Оновлення checkpointer

**Файл:** `src/agents/langgraph/checkpointer.py`

- Вже використовує PostgreSQL через `DATABASE_URL`
- Переконатись що connection string правильний
- Можливо додати явне створення таблиць checkpoints

### 6. Тестування

- Створити тести для `PostgresSessionStore`
- Створити тести для `PostgresMessageStore`
- Перевірити міграцію даних
- Перевірити що всі операції працюють

## Порядок виконання

1. **Створити SQL скрипт** (`create_all_tables_postgresql.sql`)
2. **Запустити SQL скрипт** в Railway PostgreSQL
3. **Створити скрипт міграції даних** (`migrate_data_from_supabase.py`)
4. **Запустити міграцію даних** (з Supabase в PostgreSQL)
5. **Оновити код** (замінити Supabase client на PostgreSQL)
6. **Оновити environment variables** (додати `DATABASE_URL` для Railway)
7. **Тестувати** на staging
8. **Деплой** в production

## Важливі моменти

- **Connection string:** `postgresql://postgres:ZxEqgWqgzcZNvMNwhYykInpyxKDjNitk@postgres.railway.internal:5432/railway`