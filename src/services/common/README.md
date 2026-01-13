# 🚨 Common Service — Бібліотека Помилок

> **Роль:** "Exception Library" (Бібліотека Помилок)
> **Відповідальність:** Централізовані, типізовані класи виключень для всього проекту.

Це **контракт помилок**.
Замість `raise Exception("Щось пішло не так")`, ми кидаємо конкретні типи, які можна ловити і обробляти.

---

## 🏗️ Структура

```
src/services/common/
├── __init__.py         # Експорти всіх виключень
└── exceptions.py       # ✅ Класи помилок
```

---

## 🛠️ Доступні Виключення

| Клас | Призначення | Де використовується |
| :--- | :--- | :--- |
| **`ServiceUnavailableError`** | База для всіх помилок недоступності сервісів (DB, API). | Базовий клас. |
| **`CatalogUnavailableError`** | Postgres з товарами не відповідає. | `CatalogService` |
| **`OrderCreationError`** | Не вдалося створити замовлення (CRM/DB). | `OrderService` |
| **`DuplicateOrderError`** | Юзер намагається зробити дубль замовлення. | `OrderService` |
| **`ImageValidationError`** | URL картинки битий або невалідний. | Vision Pipeline |

---

## 🔗 Інтеграція (Usage Map)

```python
# src/services/catalog/catalog_service.py
from src.services.common import CatalogUnavailableError

if RAISE_ON_CATALOG_ERROR:
    raise CatalogUnavailableError(f"Search failed: {error_msg}")
```

```python
# src/services/orders/order_service.py
from src.services.common import ServiceUnavailableError

if not crm_response.ok:
    raise ServiceUnavailableError("CRM", f"Status {crm_response.status}")
```

---

## ⚙️ Навіщо це потрібно?

### 1. Типізований Error Handling
Замість:
```python
try:
    result = await catalog.search(...)
except Exception as e:  # 🤷 Що це? Мережа? База? Баг?
    ...
```
Маємо:
```python
try:
    result = await catalog.search(...)
except CatalogUnavailableError:  # ✅ Тепер я знаю, що база "ляг"
    return fallback_response
except ImageValidationError as e:  # ✅ URL битий
    log_warning(f"Bad image: {e.url}")
```

### 2. Metadata в Помилках
Кожен клас зберігає корисні дані:
```python
class DuplicateOrderError:
    session_id: str
    existing_order_id: str | None
```
Це дозволяє логувати деталі без парсингу тексту.

---

## 📝 Вердикт
Це **фундамент надійності**.
Маленький модуль, але він робить код передбачуваним.
Без нього ми б ловили `Exception` і гадали, що сталося.
