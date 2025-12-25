# ЗАЛІЗОБЕТОННИЙ ДВИГУН v6 - Міграція Supabase → PostgreSQL

## WORKING_BRIEF

**goal:** Повний перехід з Supabase REST API на прямий PostgreSQL (Railway), зберігаючи всі дані та функціональність без downtime.

**scope_in:**
- Створення всіх таблиць в PostgreSQL Railway ✅ VERIFIED
- Міграція даних з Supabase в PostgreSQL
- Заміна Supabase client на psycopg в коді
- Оновлення всіх stores (SessionStore, MessageStore, WebhookDedupeStore)
- Оновлення workers (summarization, followups, llm_usage, crm)
- Тестування та валідація

**scope_out:**
- Встановлення pgvector extension (поки що BYTEA для embeddings)
- Зміна структури таблиць (тільки міграція даних)
- Зміна бізнес-логіки

**facts:**
- ✅ 14 таблиць створені в PostgreSQL Railway
- ✅ Connection string: `postgresql://postgres:ZxEqgWqgzcZNvMNwhYykInpyxKDjNitk@switchback.proxy.rlwy.net:30044/railway`
- ✅ Supabase все ще працює (паралельна робота можлива)
- ✅ LangGraph checkpointer вже використовує PostgreSQL через DATABASE_URL
- ⚠️ pgvector extension не встановлено (embeddings як BYTEA)

**unknowns:**
- Скільки даних в Supabase (чи потрібна batch міграція)
- Чи є активні сесії під час міграції
- Чи потрібен rollback план

**next_verification:**
- Перевірити кількість записів в Supabase таблицях
- Перевірити що PostgreSQL таблиці порожні (готові до міграції)

---

## TASK_TYPE_AND_MODE

**task_type:** DATA_PIPELINE + ARCHITECTURE

**why:** 
- Міграція даних між БД (DATA_PIPELINE)
- Зміна архітектури з REST API на direct DB (ARCHITECTURE)

**primary_risk:** 
- Втрата даних під час міграції
- Downtime під час перемикання
- Несумісність даних між Supabase та PostgreSQL

**fastest_proof:**
- Підрахунок записів в Supabase vs PostgreSQL
- Тестовий запис/читання в PostgreSQL через psycopg

**mode:** MODE_C_GUIDED_IMPLEMENTATION
- Репо доступний
- Код можна редагувати
- Можна запускати тести та перевірки

---

## FINDINGS (FACT ONLY)

### FACT: Таблиці створені
**Evidence:**
```bash
python scripts/run_sql_schema.py
# Output: ✅ Found 14 tables
```

**Tables verified:**
- agent_sessions, crm_orders, llm_traces, llm_usage, messages
- mirt_memories, mirt_memory_summaries, mirt_profiles
- order_items, orders, products, sitniks_chat_mappings
- users, webhook_dedupe

### FACT: SupabaseSessionStore використовує REST API
**Evidence:** `src/services/supabase_store.py:177-182`
```python
response = (
    client.table(self.table_name)
    .select("state")
    .eq("session_id", session_id)
    .limit(1)
    .execute()
)
```

### FACT: MessageStore використовує Supabase client
**Evidence:** `src/services/message_store.py:49-74`
```python
class SupabaseMessageStore:
    def __init__(self, client: Client, table: str = DBTable.MESSAGES):
        self.client = client
        self.table = table
```

### FACT: WebhookDedupeStore використовує Supabase
**Evidence:** `src/services/webhook_dedupe.py:63-66`
```python
self.db.table("webhook_dedupe")
```

### ASSUMPTION: Дані в Supabase потрібно мігрувати
**Hypothesis:** Є активні сесії та історія повідомлень
**Verify:** Підрахунок записів в Supabase таблицях

---

## RISKS

1. **Втрата даних під час міграції**
   - **Mitigation:** Dual-write під час міграції, валідація після

2. **Downtime під час перемикання**
   - **Mitigation:** Feature flag для поступового перемикання

3. **Несумісність даних (JSONB структури)**
   - **Mitigation:** Тестова міграція однієї сесії, перевірка структури

4. **Проблеми з connection pool**
   - **Mitigation:** Тестування pool під навантаженням

---

## OPTIONS_AND_CHOICE

### Option 1: Big Bang Migration (не рекомендовано)
**Pros:**
- Швидко
- Просто

**Cons:**
- Високий ризик втрати даних
- Потенційний downtime
- Немає rollback

**Risk:** ВИСОКИЙ

### Option 2: Dual-Write + Gradual Cutover (рекомендовано) ✅
**Pros:**
- Безпечно (дані в обох БД)
- Можливість rollback
- Поступове перемикання

**Cons:**
- Складніше (потрібен dual-write)
- Більше коду

**Risk:** СЕРЕДНІЙ

### Option 3: One-Time Migration + Cutover
**Pros:**
- Чисто (один раз)
- Простіше ніж dual-write

**Cons:**
- Потрібен maintenance window
- Ризик втрати нових даних під час міграції

**Risk:** СЕРЕДНІЙ-ВИСОКИЙ

**DECISION: Option 2 (Dual-Write + Gradual Cutover)**
**Why:** Найбезпечніший шлях з можливістю rollback та поступовим перемиканням.

---

## PLAN

### Phase 1: Підготовка та аналіз (VERIFY FIRST)

#### Step 1.1: Підрахунок даних в Supabase
**ACTION:**
```python
# scripts/analyze_supabase_data.py
# Підрахувати записи в кожній таблиці
```

**VERIFY:**
- Вивід: кількість записів по таблицях
- Визначити критичні таблиці (найбільше даних)

**ARTIFACT:** `scripts/analyze_supabase_data.py` + вивід

**RISK:** Низький

---

#### Step 1.2: Перевірка структури даних
**ACTION:**
```python
# Витягнути 1-2 приклади записів з Supabase
# Перевірити JSONB структури
```

**VERIFY:**
- Приклади записів з agent_sessions.state
- Перевірка що структура сумісна з PostgreSQL

**ARTIFACT:** Приклади JSONB структур

**RISK:** Низький

---

### Phase 2: Створення PostgreSQL stores

#### Step 2.1: Connection Pool Manager
**ACTION:**
Створити `src/services/postgres_pool.py`:
- Singleton AsyncConnectionPool
- Налаштування через config.py
- Health check метод

**VERIFY:**
```python
# Тест підключення
from src.services.postgres_pool import get_postgres_pool
pool = await get_postgres_pool()
async with pool.connection() as conn:
    await conn.execute("SELECT 1")
```

**ARTIFACT:** `src/services/postgres_pool.py` + unit test

**RISK:** Низький

**DEPENDS:** None

---

#### Step 2.2: PostgresSessionStore
**ACTION:**
Створити `src/services/postgres_store.py`:
- Реалізувати `PostgresSessionStore` з методами:
  - `get(session_id)` - SELECT з agent_sessions
  - `save(session_id, state)` - UPSERT в agent_sessions
  - `delete(session_id)` - DELETE з agent_sessions
- Використовувати postgres_pool
- Serialization як в SupabaseSessionStore

**VERIFY:**
```python
# Unit test
store = PostgresSessionStore()
state = store.get("test_session")
store.save("test_session", state)
retrieved = store.get("test_session")
assert retrieved == state
```

**ARTIFACT:** `src/services/postgres_store.py` + tests

**RISK:** Середній

**DEPENDS:** Step 2.1

---

#### Step 2.3: PostgresMessageStore
**ACTION:**
Створити `PostgresMessageStore` в `src/services/message_store.py`:
- Методи: append, list, delete
- Використовувати postgres_pool

**VERIFY:**
```python
# Unit test
store = PostgresMessageStore()
msg = StoredMessage(session_id="test", role="user", content="test")
store.append(msg)
messages = store.list("test")
assert len(messages) == 1
```

**ARTIFACT:** Оновлений `src/services/message_store.py` + tests

**RISK:** Середній

**DEPENDS:** Step 2.1

---

#### Step 2.4: PostgresWebhookDedupeStore
**ACTION:**
Оновити `src/services/webhook_dedupe.py`:
- Замінити Supabase client на postgres_pool
- Реалізувати через psycopg

**VERIFY:**
```python
# Unit test
store = PostgresWebhookDedupeStore()
is_dup = store.check_and_mark("test_key")
assert not is_dup
is_dup = store.check_and_mark("test_key")
assert is_dup
```

**ARTIFACT:** Оновлений `src/services/webhook_dedupe.py` + tests

**RISK:** Низький

**DEPENDS:** Step 2.1

---

### Phase 3: Dual-Write Implementation

#### Step 3.1: Dual-Write SessionStore
**ACTION:**
Створити `DualWriteSessionStore`:
- Записує в обидві БД (Supabase + PostgreSQL)
- Читає з PostgreSQL (fallback на Supabase)
- Логує помилки

**VERIFY:**
```python
# Integration test
store = DualWriteSessionStore()
state = store.get("test")
store.save("test", state)
# Перевірити що є в обох БД
```

**ARTIFACT:** `src/services/dual_write_store.py` + tests

**RISK:** Середній

**DEPENDS:** Step 2.2

---

#### Step 3.2: Dual-Write MessageStore
**ACTION:**
Створити `DualWriteMessageStore`:
- Аналогічно до SessionStore

**VERIFY:**
```python
# Integration test
store = DualWriteMessageStore()
store.append(msg)
# Перевірити що є в обох БД
```

**ARTIFACT:** Оновлений `src/services/message_store.py` + tests

**RISK:** Середній

**DEPENDS:** Step 2.3

---

#### Step 3.3: Feature Flag для Dual-Write
**ACTION:**
Додати в `config.py`:
```python
ENABLE_DUAL_WRITE: bool = Field(default=False)
POSTGRES_PRIMARY: bool = Field(default=False)  # Читати з PostgreSQL
```

**VERIFY:**
- Зміна прапорців змінює поведінку
- Логи показують яка БД використовується

**ARTIFACT:** Оновлений `src/conf/config.py`

**RISK:** Низький

**DEPENDS:** Step 3.1, Step 3.2

---

### Phase 4: Міграція даних

#### Step 4.1: Скрипт міграції даних
**ACTION:**
Створити `scripts/migrate_data_from_supabase.py`:
- Підключення до обох БД
- Batch міграція (по 1000 записів)
- Логування прогресу
- Resume support (перевірка що вже мігровано)
- Валідація після міграції

**VERIFY:**
```bash
python scripts/migrate_data_from_supabase.py --dry-run
# Перевірити що скрипт правильно підраховує записи
python scripts/migrate_data_from_supabase.py --table agent_sessions
# Перевірити що дані мігруються
```

**ARTIFACT:** `scripts/migrate_data_from_supabase.py`

**RISK:** Високий (можлива втрата даних)

**DEPENDS:** Step 2.2, Step 2.3

---

#### Step 4.2: Тестова міграція однієї сесії
**ACTION:**
Мігрувати 1 тестову сесію з Supabase в PostgreSQL

**VERIFY:**
```sql
-- В Supabase
SELECT * FROM agent_sessions WHERE session_id = 'test_session';

-- В PostgreSQL
SELECT * FROM agent_sessions WHERE session_id = 'test_session';

-- Порівняти JSONB структури
```

**ARTIFACT:** SQL запити + порівняння

**RISK:** Низький

**DEPENDS:** Step 4.1

---

#### Step 4.3: Повна міграція даних
**ACTION:**
Запустити міграцію всіх таблиць:
1. agent_sessions (критично!)
2. messages (критично!)
3. users
4. products
5. orders + order_items
6. crm_orders
7. sitniks_chat_mappings
8. mirt_profiles
9. mirt_memories
10. mirt_memory_summaries
11. llm_usage
12. llm_traces
13. webhook_dedupe

**VERIFY:**
```python
# Після міграції
# Підрахунок записів в обох БД
# Порівняння кількості
```

**ARTIFACT:** Логи міграції + звіт валідації

**RISK:** Високий

**DEPENDS:** Step 4.2

---

### Phase 5: Перемикання на PostgreSQL

#### Step 5.1: Увімкнути Dual-Write
**ACTION:**
Встановити `ENABLE_DUAL_WRITE=true` в production

**VERIFY:**
- Логи показують запис в обидві БД
- Немає помилок
- Моніторинг показує нормальну роботу

**ARTIFACT:** Логи + метрики

**RISK:** Середній

**DEPENDS:** Step 4.3

---

#### Step 5.2: Перемикання читання на PostgreSQL
**ACTION:**
Встановити `POSTGRES_PRIMARY=true`

**VERIFY:**
- Логи показують читання з PostgreSQL
- Немає помилок
- Сесії працюють нормально

**ARTIFACT:** Логи + метрики

**RISK:** Високий

**DEPENDS:** Step 5.1

---

#### Step 5.3: Вимкнути Supabase запис
**ACTION:**
Встановити `ENABLE_DUAL_WRITE=false`
Видалити Supabase client з коду

**VERIFY:**
- Тільки PostgreSQL використовується
- Немає помилок
- Всі операції працюють

**ARTIFACT:** Оновлений код без Supabase client

**RISK:** Середній

**DEPENDS:** Step 5.2 (через 24-48 годин моніторингу)

---

### Phase 6: Оновлення workers та інших компонентів

#### Step 6.1: Оновити workers
**ACTION:**
Оновити `src/workers/tasks/*.py`:
- summarization.py
- followups.py
- llm_usage.py
- crm.py

**VERIFY:**
- Workers запускаються
- Дані правильно читаються/пишуться

**ARTIFACT:** Оновлені workers

**RISK:** Середній

**DEPENDS:** Step 5.3

---

#### Step 6.2: Оновити observability
**ACTION:**
Оновити `src/services/observability.py` для llm_traces

**VERIFY:**
- Трейси записуються в PostgreSQL

**ARTIFACT:** Оновлений observability.py

**RISK:** Низький

**DEPENDS:** Step 5.3

---

## VERIFICATION_MAP

### AC1: Всі таблиці створені в PostgreSQL
**Status:** ✅ VERIFIED
**Evidence:**
```bash
python scripts/run_sql_schema.py
# ✅ Found 14 tables
```
**Repro:** `python scripts/run_sql_schema.py`

---

### AC2: PostgreSQL stores працюють (get/save/delete)
**Status:** ⏳ NOT_VERIFIED
**Evidence:** Поки що немає
**Repro:** Unit tests для PostgresSessionStore, PostgresMessageStore
**Notes:** Потрібно створити в Phase 2

---

### AC3: Міграція даних завершена без втрат
**Status:** ⏳ NOT_VERIFIED
**Evidence:** Поки що немає
**Repro:** Порівняння кількості записів до/після міграції
**Notes:** Потрібно виконати в Phase 4

---

### AC4: Dual-write працює (дані в обох БД)
**Status:** ⏳ NOT_VERIFIED
**Evidence:** Поки що немає
**Repro:** Перевірка що записи є в обох БД після save
**Notes:** Потрібно виконати в Phase 3

---

### AC5: Перемикання на PostgreSQL без downtime
**Status:** ⏳ NOT_VERIFIED
**Evidence:** Поки що немає
**Repro:** Моніторинг під час перемикання
**Notes:** Потрібно виконати в Phase 5

---

### AC6: Всі workers працюють з PostgreSQL
**Status:** ⏳ NOT_VERIFIED
**Evidence:** Поки що немає
**Repro:** Запуск workers, перевірка логів
**Notes:** Потрібно виконати в Phase 6

---

## NEXT_REQUEST

**Що робити далі:**

1. **IMMEDIATE:** Створити скрипт для підрахунку даних в Supabase (Step 1.1)
2. **NEXT:** Створити postgres_pool.py (Step 2.1)
3. **AFTER:** Реалізувати PostgresSessionStore (Step 2.2)

**Артефакти які потрібні:**
- Кількість записів в Supabase таблицях
- Приклади JSONB структур з agent_sessions.state

**Блокування:**
- Немає (можна починати з Phase 2)

