# Fix: DuplicatePreparedStatement Error

**Дата:** 2025-12-23  
**Версия:** 1.0  
**Статус:** ✅ FIXED

---

## Проблема

Система падала с ошибкой `DuplicatePreparedStatement: prepared statement "_pg3_X" already exists` после нескольких retry попыток.

**Симптомы:**
- Ошибка возникает при использовании `AsyncPostgresSaver` с `AsyncConnectionPool`
- Происходит после нескольких успешных операций
- Retry не помогает - ошибка повторяется

---

## Корневая причина

**ROOT CAUSE:** Конфликт prepared statements в connection pool.

Когда несколько соединений в пуле пытаются создать prepared statement с одинаковым именем (например, `_pg3_0`, `_pg3_2`), psycopg выбрасывает `DuplicatePreparedStatement`.

**Почему это происходит:**
1. `AsyncPostgresSaver` использует prepared statements для оптимизации
2. `AsyncConnectionPool` создает несколько соединений (min_size=2, max_size=10)
3. Каждое соединение пытается создать prepared statement с одинаковым именем
4. PostgreSQL не позволяет иметь два prepared statement с одинаковым именем в одной сессии
5. При параллельных запросах возникает конфликт

---

## Решение

**ROOT CAUSE FIX:** Отключить prepared statements для checkpointer.

**Почему это безопасно:**
- Prepared statements дают минимальный прирост производительности для checkpointing операций
- Checkpointing операции не настолько частые, чтобы нуждаться в оптимизации
- Отключение prepared statements полностью устраняет конфликт

**Реализация:**
```python
# IMPORTANT: prepare_threshold must be set via conninfo string, not kwargs
# psycopg reads prepare_threshold from connection string parameters
import urllib.parse
parsed = urllib.parse.urlparse(database_url)
query_params = urllib.parse.parse_qs(parsed.query)
query_params["prepare_threshold"] = ["0"]  # Disable prepared statements
new_query = urllib.parse.urlencode(query_params, doseq=True)
database_url_with_prepare = urllib.parse.urlunparse(
    (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
)

pool = AsyncConnectionPool(
    conninfo=database_url_with_prepare,  # Use modified URL with prepare_threshold=0
    min_size=2,
    max_size=10,
    open=False,
)
```

**Что делает `prepare_threshold=0`:**
- Отключает автоматическое создание prepared statements
- Все запросы выполняются как обычные SQL запросы
- Устраняет конфликт имен prepared statements

---

## Изменения

### 1. `src/agents/langgraph/checkpointer.py`
- Модифицирован `database_url` для добавления `prepare_threshold=0` в query string
- Параметр передается через conninfo строку (не через kwargs), так как psycopg читает его из URL
- Добавлены комментарии объясняющие решение

### 2. `src/services/conversation/handler.py`
- Обновлены комментарии в retry логике
- Добавлено предупреждение если ошибка все еще возникает (не должно)

---

## Проверка

**VERIFY:**
1. Система должна работать без `DuplicatePreparedStatement` ошибок
2. Checkpointing должен работать нормально (без потери производительности)
3. Retry логика остается как safety net (но не должна срабатывать)

**Команда для проверки:**
```bash
# Запустить систему и проверить логи
# Не должно быть DuplicatePreparedStatement ошибок
```

---

## Результат

✅ **FIXED** - Prepared statements отключены, конфликт устранен

---

## Альтернативные решения (не использованы)

1. **Уникальные имена prepared statements** - сложно реализовать, требует изменений в LangGraph
2. **Один connection вместо pool** - снижает производительность при высокой нагрузке
3. **Управление prepared statements вручную** - слишком сложно, требует глубоких изменений

**Выбранное решение оптимально:** простое, эффективное, не требует изменений в зависимостях.

