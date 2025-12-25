# PostgreSQL Schema Creation

## Створення всіх таблиць в PostgreSQL Railway

### Варіант 1: Через Railway CLI (рекомендовано)

```bash
# Встановити Railway CLI (якщо ще не встановлено)
# https://docs.railway.app/develop/cli

# Логін в Railway
railway login

# Підключитись до проекту
railway link

# Запустити SQL скрипт
railway run psql < scripts/sql/create_all_tables_postgresql.sql
```

### Варіант 2: Через Python скрипт (в Railway)

```bash
# Встановити залежності
pip install 'psycopg[binary]'

# Встановити DATABASE_URL з Railway
export DATABASE_URL="postgresql://postgres:ZxEqgWqgzcZNvMNwhYykInpyxKDjNitk@postgres.railway.internal:5432/railway"

# Запустити скрипт
python scripts/run_sql_schema.py
```

### Варіант 3: Через Railway Dashboard

1. Відкрити Railway Dashboard
2. Перейти до PostgreSQL service
3. Відкрити "Query" tab
4. Скопіювати вміст `scripts/sql/create_all_tables_postgresql.sql`
5. Вставити та виконати

### Варіант 4: Через psql (якщо є доступ до публічного хоста)

```bash
# Якщо Railway надав публічний connection string
psql "postgresql://postgres:PASSWORD@PUBLIC_HOST:PORT/railway" -f scripts/sql/create_all_tables_postgresql.sql
```

## Перевірка

Після виконання скрипту перевірте, що всі таблиці створені:

```sql
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_type = 'BASE TABLE'
ORDER BY table_name;
```

Очікувані таблиці:
- agent_sessions
- crm_orders
- llm_traces
- llm_usage
- messages
- mirt_memories
- mirt_memory_summaries
- mirt_profiles
- order_items
- orders
- products
- sitniks_chat_mappings
- users
- webhook_dedupe

## Примітки

- Скрипт є **IDEMPOTENT** - його можна запускати багато разів без помилок
- Extensions `vector` (pgvector) та `pg_cron` будуть створені автоматично
- RLS policies закоментовані (не потрібні для Railway single-tenant)
- LangGraph checkpoints таблиці створюються автоматично при першому використанні checkpointer

