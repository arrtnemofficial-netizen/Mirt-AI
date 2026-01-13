# 📦 Orders Service — Замовлення (Частково Деактивований)

> **Роль:** "Order Data Contract" (Контракт Даних Замовлення)
> **Відповідальність:** Pydantic-моделі для замовлень та валідація даних перед відправкою в CRM.

---

## ⚠️ ЗАСТЕРЕЖЕННЯ (УВАГА!)

> ⚠️ **ЧАСТКОВИЙ STUB:** `OrderService` є **заглушкою** (MOCK).
> Ви раніше вимкнули локальне збереження замовлень у Postgres

> 🔴 **НЕ ВИДАЛЯТИ:** Модуль `order_model.py` **ВИКОРИСТОВУЄТЬСЯ** і є критичним!

---

## 🏗️ Структура

```
src/services/orders/
├── __init__.py         # Експорти
├── order_service.py    # ⚠️ STUB (заглушка, нічого не робить)
└── order_model.py      # ✅ ACTIVE (моделі + валідація)
```

---

## 🔍 Детальний Аналіз

### 1. `OrderService` (order_service.py) — STUB
```python
async def create_order(self, order_data):
    # [USER-OVERRIDE] Disabled local order persistence
    # "НЕТ Я ЖЕ ОТКОЗАЛСЯ ОТ ОРДЕРС!!"
    logger.info("OrderService.create_order: MOCK SKIPPED")
    return "mock_skipped_id"
```
**Статус:** Заглушка. Не записує нічого в базу.
**Чому не видаляти:** `deps.py` імпортує `OrderService`. Видалення зламає імпорти.

---

### 2. `order_model.py` — КРИТИЧНО ВАЖЛИВИЙ ✅

**Pydantic-моделі:**
| Клас | Призначення |
| :--- | :--- |
| `Order` | Повна структура замовлення для CRM. |
| `OrderItem` | Один товар у замовленні (product_id, size, color, price). |
| `CustomerInfo` | Дані клієнта (ПІБ, телефон, місто, НП). |
| `OrderStatus` | Enum: NEW, PAID, SHIPPED, DELIVERED, CANCELLED. |
| `PaymentMethod` | Enum: FULL_PREPAY, PARTIAL_PREPAY, CASH_ON_DELIVERY. |
| `DeliveryMethod` | Enum: NOVA_POSHTA, UKRPOSHTA, SELF_PICKUP. |

**Функції:**
| Функція | Призначення |
| :--- | :--- |
| `validate_order_data()` | Перевіряє, чи є всі поля для замовлення. |
| `build_missing_data_prompt()` | Генерує повідомлення "Вкажіть ПІБ та телефон 📝". |
| `Order.to_crm_payload()` | Конвертує в формат для Snitkix CRM. |

---

## 🔗 Інтеграція (Usage Map)

| Файл | Що імпортує |
| :--- | :--- |
| `src/integrations/crm/base.py` | `Order`, `OrderStatus` |
| `src/agents/pydantic/deps.py` | `OrderService` (як `Database` alias) |

---

## ❓ Чи можна видалити?

**НІ.**

1.  **`order_model.py`** — використовується CRM інтеграцією для формування замовлень.
2.  **`OrderService`** — stub, але `deps.py` імпортує його. Видалення = `ImportError`.

### Що можна зробити?
Якщо хочете "почистити":
1.  Залиште `order_model.py` як є (він потрібен).
2.  `OrderService` можна перейменувати на `OrderServiceStub` для ясності.

---

## 📝 Вердикт
**Не видаляти.**
*   `order_model.py` = живий код, критичний для CRM.
*   `order_service.py` = stub, але потрібен для сумісності імпортів.
