# Аналіз таблиць, які можуть не заповнюватися

## Таблиці, які НЕ заповнюються автоматично (або рідко)

### 1. `products` ⚠️ НЕ ЗАПОВНЮЄТЬСЯ АВТОМАТИЧНО

**Проблема**: Таблиця `products` заповнюється **вручну** при імпорті каталогу, не автоматично.

**Чому**:
- Каталог товарів імпортується зовнішнім скриптом або migration
- Немає автоматичного механізму синхронізації з джерелом даних
- Потрібно запускати імпорт вручну після оновлення каталогу

**Як заповнити**:
```sql
-- Перевірка чи є товари
SELECT COUNT(*) FROM products;

-- Якщо порожня - потрібно запустити імпорт каталогу
-- (зовнішній скрипт або migration)
```

**Рішення**: 
- Створити автоматичний імпорт каталогу з джерела даних
- Або додати scheduled task для синхронізації

---

### 2. `llm_traces` ⚠️ МОЖЕ НЕ ЗАПОВНЮВАТИСЬ

**Проблема**: Таблиця `llm_traces` заповнюється тільки якщо `ENABLE_OBSERVABILITY=True` (default=True, але може бути вимкнено).

**Чому**:
- `AsyncTracingService` перевіряє `self._enabled` перед записом
- Якщо `ENABLE_OBSERVABILITY=False` або `DATABASE_URL` не налаштовано, traces не записуються

**Код**:
```python
# src/services/observability/observability.py:319
async def log_trace(...):
    if not self._enabled:
        return  # НЕ ЗАПИСУЄТЬСЯ!
```

**Як перевірити**:
```sql
-- Перевірка чи є traces
SELECT COUNT(*) FROM llm_traces WHERE created_at > NOW() - INTERVAL '1 day';

-- Перевірка налаштування
-- В .env або settings: ENABLE_OBSERVABILITY=True
```

**Рішення**: 
- Переконатися що `ENABLE_OBSERVABILITY=True` в production
- Або вимкнути якщо не потрібно (для performance)

---

### 3. `mirt_memories` ⚠️ МОЖЕ НЕ ЗАПОВНЮВАТИСЬ

**Проблема**: Таблиця `mirt_memories` заповнюється тільки якщо:
1. Memory system enabled (`DATABASE_URL` налаштовано)
2. Є важливі факти з `importance >= 0.6` та `surprise >= 0.4`
3. Memory update node викликається після ключових станів

**Чому**:
- Memory system має gating механізм - зберігає тільки важливі факти
- Якщо всі факти мають низьку importance/surprise, нічого не зберігається
- Memory update node може не викликатися для всіх діалогів

**Код**:
```python
# src/services/memory/facts.py:37-51
if not bypass_gating:
    if fact.importance < MIN_IMPORTANCE_TO_STORE:  # 0.6
        return None  # НЕ ЗАПИСУЄТЬСЯ!
    if fact.surprise < MIN_SURPRISE_TO_STORE:  # 0.4
        return None  # НЕ ЗАПИСУЄТЬСЯ!
```

**Як перевірити**:
```sql
-- Перевірка чи є memories
SELECT COUNT(*) FROM mirt_memories WHERE created_at > NOW() - INTERVAL '1 day';

-- Перевірка memory system
-- В settings: DATABASE_URL має бути налаштовано
```

**Рішення**: 
- Переконатися що memory system enabled
- Або знизити thresholds якщо потрібно більше фактів

---

### 4. `mirt_profiles` ⚠️ МОЖЕ НЕ ЗАПОВНЮВАТИСЬ

**Проблема**: Таблиця `mirt_profiles` заповнюється тільки якщо:
1. Memory system enabled
2. Викликається `get_or_create_profile()` або `create_profile()`
3. Memory context node викликається (що залежить від routing)

**Чому**:
- Profile створюється тільки при першому виклику memory context
- Якщо memory context node не викликається (наприклад, для коротких діалогів), profile не створюється
- Memory system може бути disabled

**Код**:
```python
# src/services/memory/profiles.py:43-47
async def get_or_create_profile(self, user_id: str):
    existing = await self.get_profile(user_id)
    if existing:
        return existing
    return await self.create_profile(user_id)  # Створюється тільки тут
```

**Як перевірити**:
```sql
-- Перевірка чи є profiles
SELECT COUNT(*) FROM mirt_profiles WHERE created_at > NOW() - INTERVAL '1 day';
```

**Рішення**: 
- Переконатися що memory context node викликається
- Або створювати profile при першому повідомленні користувача

---

### 5. `mirt_memory_summaries` ⚠️ МОЖЕ НЕ ЗАПОВНЮВАТИСЬ

**Проблема**: Таблиця `mirt_memory_summaries` заповнюється тільки при summarization inactive users (scheduled task).

**Чому**:
- Summarization запускається через Celery scheduled task
- Тільки для inactive users (не активні протягом retention window)
- Якщо Celery не налаштовано або task не запускається, summaries не створюються

**Код**:
```python
# src/services/summarization/summarization.py:update_user_summary()
# Викликається тільки з Celery task
```

**Як перевірити**:
```sql
-- Перевірка чи є summaries
SELECT COUNT(*) FROM mirt_memory_summaries WHERE created_at > NOW() - INTERVAL '7 days';
```

**Рішення**: 
- Переконатися що Celery scheduled task налаштовано
- Або запускати summarization вручну

---

### 6. `checkpoint_blobs` ⚠️ РІДКО ЗАПОВНЮЄТЬСЯ

**Проблема**: Таблиця `checkpoint_blobs` заповнюється тільки якщо checkpoint > 1MB (рідко).

**Чому**:
- LangGraph зберігає checkpoints в `checkpoints` table як JSONB
- Якщо checkpoint занадто великий (>1MB), він зберігається в `checkpoint_blobs`
- Більшість checkpoints < 1MB, тому `checkpoint_blobs` рідко заповнюється

**Як перевірити**:
```sql
-- Перевірка чи є blobs
SELECT COUNT(*) FROM checkpoint_blobs;
```

**Рішення**: 
- Це нормально - blobs використовуються рідко
- Якщо потрібно, можна зменшити розмір checkpoints

---

### 7. `checkpoint_migrations` ⚠️ РІДКО ЗАПОВНЮЄТЬСЯ

**Проблема**: Таблиця `checkpoint_migrations` заповнюється тільки при міграціях checkpoint schema (рідко).

**Чому**:
- Міграції checkpoint schema відбуваються рідко (при зміні структури state)
- Якщо schema не змінюється, міграції не виконуються

**Як перевірити**:
```sql
-- Перевірка чи є міграції
SELECT COUNT(*) FROM checkpoint_migrations;
```

**Рішення**: 
- Це нормально - міграції відбуваються рідко
- Якщо потрібно, можна запустити міграцію вручну

---

## Підсумок

### Таблиці, які МОЖУТЬ не заповнюватися:

1. **`products`** - заповнюється вручну при імпорті каталогу
2. **`llm_traces`** - якщо `ENABLE_OBSERVABILITY=False`
3. **`mirt_memories`** - якщо memory disabled або всі факти мають низьку importance
4. **`mirt_profiles`** - якщо memory disabled або memory context node не викликається
5. **`mirt_memory_summaries`** - якщо Celery scheduled task не налаштовано
6. **`checkpoint_blobs`** - рідко (тільки якщо checkpoint > 1MB)
7. **`checkpoint_migrations`** - рідко (тільки при міграціях schema)

### Таблиці, які ЗАВЖДИ заповнюються (якщо система працює):

- ✅ `users` - при кожному повідомленні
- ✅ `messages` - при кожному повідомленні
- ✅ `orders` - після payment proof
- ✅ `order_items` - разом з orders
- ✅ `sitniks_chat_mappings` - при first touch
- ✅ `llm_usage` - при кожному LLM виклику
- ✅ `checkpoints` - автоматично LangGraph
- ✅ `checkpoint_writes` - автоматично LangGraph
- ✅ `agent_sessions` - при збереженні стану
- ✅ `crm_orders` - при створенні замовлення в CRM
- ✅ `webhook_dedupe` - при обробці webhook

## Рекомендації

1. **Перевірити налаштування**:
   - `ENABLE_OBSERVABILITY=True` для `llm_traces`
   - `DATABASE_URL` налаштовано для memory system
   - Celery scheduled tasks налаштовано для summarization

2. **Заповнити `products` вручну**:
   - Запустити імпорт каталогу
   - Або створити автоматичний імпорт

3. **Перевірити memory system**:
   - Переконатися що memory context node викликається
   - Перевірити thresholds для importance/surprise

4. **Моніторинг**:
   - Додати alerts для порожніх таблиць (якщо очікуються дані)
   - Логувати коли таблиці не заповнюються

