# Политика обработки ошибок (Error Handling Policy)

**Дата:** 2025-12-23  
**Версия:** 1.0  
**Статус:** ACTIVE

---

## Принципы

### 1. Запрещены Silent Failures

**Правило:** Все `except` блоки должны логировать ошибки.

**Исключения:**
- Ожидаемые ошибки в dev окружении (например, Redis недоступен) → `logger.debug()`
- Graceful degradation для не-критичных операций → `logger.warning()` или `logger.debug()`

**Примеры:**

❌ **ПЛОХО:**
```python
except Exception:
    return None  # Silent failure - невозможно диагностировать
```

✅ **ХОРОШО:**
```python
except (redis.ConnectionError, redis.TimeoutError) as e:
    logger.debug("[COMPONENT] Redis unavailable (expected in dev): %s", type(e).__name__)
    return None
except Exception as e:
    logger.warning("[COMPONENT] Unexpected error: %s", type(e).__name__)
    return None
```

---

### 2. Узкие исключения вместо broad catch

**Правило:** Использовать конкретные типы исключений вместо `except Exception:`.

**Исключения:**
- Топ-уровневые обработчики (например, в FastAPI middleware)
- Graceful degradation для внешних сервисов

**Примеры:**

❌ **ПЛОХО:**
```python
try:
    result = risky_operation()
except Exception:  # Слишком широко
    logger.error("Failed")
```

✅ **ХОРОШО:**
```python
try:
    result = risky_operation()
except (ValueError, TypeError) as e:
    logger.warning("[COMPONENT] Invalid input: %s", type(e).__name__)
except (ConnectionError, TimeoutError) as e:
    logger.warning("[COMPONENT] Network error: %s", type(e).__name__)
except Exception as e:
    logger.error("[COMPONENT] Unexpected error: %s", type(e).__name__)
```

---

### 3. Structured Logging

**Правило:** Все логи должны содержать структурированную информацию.

**Обязательные поля:**
- `component`: Название компонента (например, `[CATALOG:CACHE]`)
- `operation`: Операция (например, `get_product_by_id`)
- `session_id`: Если доступен (для трассировки)
- `error_type`: Тип ошибки (`type(e).__name__`)

**Примеры:**

✅ **ХОРОШО:**
```python
logger.warning(
    "[CATALOG:CACHE] Failed to decode cached JSON for key '%s': %s",
    key,
    type(e).__name__
)
```

---

### 4. Уровни логирования

- **ERROR**: Критичные ошибки, которые влияют на функциональность
- **WARNING**: Проблемы, которые не критичны, но требуют внимания
- **DEBUG**: Ожидаемые ошибки в dev окружении (Redis недоступен и т.д.)
- **INFO**: Нормальные операции

---

## Классификация ошибок

### Критичные (ERROR)
- Потеря данных
- Недоступность критичных сервисов (DB, LLM)
- Ошибки валидации бизнес-логики

### Не-критичные (WARNING/DEBUG)
- Недоступность кеша (Redis)
- Ошибки парсинга необязательных данных
- Таймауты внешних сервисов (с retry)

---

## Примеры исправлений

### Catalog Service Cache

**Было:**
```python
except Exception:
    return None
```

**Стало:**
```python
except (redis.ConnectionError, redis.TimeoutError, redis.RedisError) as e:
    logger.debug("[CATALOG:CACHE] Redis error: %s", type(e).__name__)
    return None
except Exception as e:
    logger.warning("[CATALOG:CACHE] Unexpected error: %s", type(e).__name__)
    return None
```

---

## Проверка соответствия

**Команда для проверки:**
```bash
grep -r "except.*:\s*\(pass\|continue\|$\)" src/ | grep -v "logger\|log\|track"
```

**Ожидаемый результат:** Пустой вывод (все except блоки логируют)

---

## Исключения из правил

1. **UUID нормализация** (`observability.py:398`): Fallback на UUID5 - это нормальная логика, не ошибка
2. **ImportError в optional dependencies**: Ожидаемо, можно логировать debug
3. **Топ-уровневые обработчики**: FastAPI exception handlers могут использовать broad catch

---

## Следующие шаги

1. ✅ Политика создана
2. ⏭️ Исправить все silent failures в критичных компонентах
3. ⏭️ Добавить метрики для отслеживания ошибок
4. ⏭️ Создать тесты для проверки логирования

