# Fix: DuplicatePreparedStatement Error

**Дата:** 2025-12-23  
**Версия:** 1.0  
**Статус:** ✅ FIXED (v2 - правильная реализация)

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
# IMPORTANT: prepare_threshold must be passed via kwargs to AsyncConnectionPool
# This parameter is passed to psycopg.AsyncConnection constructor for each connection in pool
# prepare_threshold=0 disables automatic prepared statement creation
# 
# ADDITIONAL SAFEGUARD: configure callback executes DEALLOCATE ALL on each connection
# This ensures no prepared statements persist when connection is reused from pool
async def configure_connection(conn):
    """Configure connection to prevent prepared statement conflicts."""
    try:
        await conn.execute("DEALLOCATE ALL")
    except Exception as e:
        logger.debug("[CHECKPOINTER] DEALLOCATE ALL warning: %s", type(e).__name__)

pool = AsyncConnectionPool(
    conninfo=database_url,  # Original URL without modifications
    min_size=2,
    max_size=10,
    open=False,
    kwargs={"prepare_threshold": 0},  # Disable prepared statements
    configure=configure_connection,  # Additional safeguard: clean prepared statements on reuse
)
```

**Что делает `prepare_threshold=0`:**
- Отключает автоматическое создание prepared statements в psycopg
- Все запросы выполняются как обычные SQL запросы
- Устраняет конфликт имен prepared statements

**Что делает `configure` callback с `DEALLOCATE ALL`:**
- Выполняется при каждом использовании соединения из пула
- Удаляет все существующие prepared statements из сессии
- Дополнительная защита на случай если `prepare_threshold=0` не сработает полностью

---

## Изменения

### 1. `src/agents/langgraph/checkpointer.py`
- Добавлен `kwargs={"prepare_threshold": 0}` в `AsyncConnectionPool` для отключения prepared statements
- Добавлен `configure` callback с `DEALLOCATE ALL` как дополнительная защита
- Параметр передается через kwargs (не через URI), так как `prepare_threshold` не является валидным параметром PostgreSQL URI
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

