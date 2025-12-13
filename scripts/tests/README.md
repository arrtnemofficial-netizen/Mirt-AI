# 🧪 MIRT AI - Supabase Table Tests

> 200+ реальних SQL тестів для перевірки всіх таблиць перед production.

---

## 📋 Як Запускати

1. Відкрий **Supabase Dashboard** → **SQL Editor**
2. Виконуй файли **по порядку**:

```
01_test_core_tables.sql          # ~40 тестів
02_test_memory_system.sql        # ~50 тестів
03_test_crm_observability.sql    # ~50 тестів
04_test_rls_functions.sql        # ~40 тестів
05_test_integration_cleanup.sql  # ~30 тестів + cleanup
```

---

## 📊 Що Тестується

| Suite | Файл | Таблиці |
|-------|------|---------|
| 1-6 | `01_test_core_tables.sql` | users, agent_sessions, messages, products, orders, order_items |
| 7-11 | `02_test_memory_system.sql` | mirt_profiles, mirt_memories, mirt_memory_summaries |
| 12-16 | `03_test_crm_observability.sql` | crm_orders, sitniks_chat_mappings, llm_traces, llm_usage, checkpoints |
| 17-24 | `04_test_rls_functions.sql` | RLS policies, functions, triggers, indexes, constraints |
| 25-30 | `05_test_integration_cleanup.sql` | Full flow simulation, data integrity, cleanup |

---

## ✅ Очікувані Результати

Кожен тест повинен:
- Повернути дані (SELECT) або
- Показати `INSERT 0 1` / `UPDATE 1` (DML) або
- НЕ показати помилку

### Приклад Успішного Тесту

```sql
-- TEST 7.3: Verify completeness_score auto-calculation
SELECT user_id, completeness_score FROM mirt_profiles WHERE user_id = 'test_memory_user_001';
-- Result: completeness_score > 0.5 ✓
```

### Приклад Провалу

```sql
-- ERROR: relation "some_table" does not exist
-- FAIL: Таблиця не створена!
```

---

## 🧹 Cleanup

Після тестування запусти cleanup з `05_test_integration_cleanup.sql`:

```sql
-- Uncomment and run:
DELETE FROM llm_traces WHERE session_id LIKE '%test%';
DELETE FROM messages WHERE session_id LIKE '%test%';
DELETE FROM crm_orders WHERE session_id LIKE '%test%';
DELETE FROM mirt_memories WHERE user_id LIKE '%test%';
DELETE FROM mirt_profiles WHERE user_id LIKE '%test%';
DELETE FROM agent_sessions WHERE session_id LIKE '%test%';
DELETE FROM products WHERE sku LIKE 'TEST%';
DELETE FROM users WHERE external_id LIKE 'test%';
```

---

## 🔧 Якщо Тест Провалився

| Помилка | Причина | Рішення |
|---------|---------|---------|
| `relation does not exist` | Таблиця не створена | Запусти відповідний SQL migration |
| `column does not exist` | Схема застаріла | Запусти ALTER TABLE migration |
| `permission denied` | RLS блокує | Перевір що використовуєш service_role |
| `duplicate key` | Тест вже запускався | Запусти cleanup |
| `foreign key violation` | Залежність відсутня | Запусти тести по порядку |

---

## 📝 Checklist

- [ ] `01_test_core_tables.sql` - всі SELECT повертають дані
- [ ] `02_test_memory_system.sql` - completeness_score > 0
- [ ] `03_test_crm_observability.sql` - checkpoints існують
- [ ] `04_test_rls_functions.sql` - vector extension встановлено
- [ ] `05_test_integration_cleanup.sql` - cleanup видаляє всі test дані
- [ ] Фінальний summary показує "ALL TESTS PASSED"

---

*Created: 2025-12-11*
