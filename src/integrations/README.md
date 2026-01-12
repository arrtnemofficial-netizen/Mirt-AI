# 🔌 src/integrations — Зовнішній Світ (External World)

> **Роль:** "Ports & Adapters"
> **Відповідальність:** Спілкування з зовнішніми системами (CRM, ManyChat, InstagramAPI).

Тут архітектура стає цікавою. Ця директорія має **ДВОЯКУ ПРИРОДУ** (Dual Nature).
Ми повинні чітко розрізняти **Adapters** (ми викликаємо їх) та **Drivers** (вони викликають нас).

---

## 📊 Архітектурна Карта (The Honest Truth)

### 1. 📤 Adapters (Вихідні)
**Приклад:** `src/integrations/crm/` (Sitniks CRM)

*   **Роль:** Інструмент, який ми використовуємо.
*   **Напрямок:** `Agents → CRM`
*   **Правило:** ❌ `crm` **НЕ МОЖЕ** імпортувати з `agents` (це порушить Dependency Loop).

### 2. 📥 Drivers (Вхідні)
**Приклад:** `src/integrations/manychat/` (Webhook, Push Client)

*   **Роль:** Точка входу, яка "будить" бота. Це фактично частина **Infrastructure Layer**, як і `src/server`.
*   **Напрямок:** `ManyChat → Agents`
*   **Правило:** ✅ `manychat` **МОЖЕ** імпортувати з `agents` (щоб запустити граф).

---

## 🏗️ Структура

```
src/integrations/
├── crm/                  # 📤 Secondary Adapter
│   ├── sitniks_chat_service.py # Клієнт CRM
│   └── order_mapper.py   # Конвертер даних
│
└── manychat/             # 📥 Primary Adapter (Driver)
    ├── webhook.py        # Вхідна точка (Router)
    ├── async_service.py  # Обробник подій (запускає Agents)
    ├── api_client.py     # API клієнт (low-level)
    └── push_client.py    # Відправка push-ів (Infrastructure)
```

---

## 🛡️ Залізобетонні Правила (Enforced)

| Модуль | Може імпортувати Agents? | Пояснення |
| :--- | :--- | :--- |
| **`crm`** | ❌ **НІ** | Це інструмент. Агент викликає CRM. CRM не знає про Агента. |
| **`manychat`** | ✅ **ТАК** | Це точка входу. ManyChat отримує webhook і каже Агенту: "Працюй!". |

> ⚠️ Ці правила перевіряються автоматично в `scripts/check_imports.py`.

---

## 📝 Вердикт

Це **найскладніша** частина для розуміння залежностей.
Ми чесно визнали, що `manychat` — це **Driver**, тому йому дозволено залежати від `agents`.
А `crm` — це **Driven**, тому він чистий.

Система залишається стабільною завдяки цьому чіткому розділенню.
