# ⚙️ src/conf — Конфігураційний Фундамент

> **Роль:** "Bedrock" (Підвалина)
> **Відповідальність:** Читання ENV змінних та надання типізованих налаштувань усій системі.

Це **НАЙНИЖЧИЙ ШАР** архітектури. Усі інші модулі імпортують з нього, він НЕ імпортує з нікого.

---

## 🏗️ Структура

```
src/conf/
├── __init__.py         # Експорти
├── config.py           # 🔧 Settings (Pydantic BaseSettings) — SSOT
└── payment_config.py   # 💳 Платіжні реквізити та форматування
```

---

## 📊 Архітектурна Позиція

```
┌─────────────────────────────────────────────────────────────┐
│                     DEPENDENCY PYRAMID                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│         src/server/      src/workers/                       │
│              ↓                ↓                              │
│         src/agents/                                          │
│              ↓                                               │
│         src/services/    src/integrations/                  │
│              ↓                ↓                              │
│         src/core/                                            │
│              ↓                                               │
│     ━━━━ src/conf/ ━━━━  ← FOUNDATION (найнижчий)           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛡️ Залізобетонні Правила

| Правило | Статус |
| :--- | :--- |
| `conf → agents` | ❌ **ЗАБОРОНЕНО** |
| `conf → services` | ❌ **ЗАБОРОНЕНО** |
| `conf → core` | ❌ **ЗАБОРОНЕНО** |
| `conf → server` | ❌ **ЗАБОРОНЕНО** |
| `conf → workers` | ❌ **ЗАБОРОНЕНО** |

> ⚠️ Ці правила перевіряються автоматично через `scripts/check_imports.py`.

---

## 🔧 config.py — Головні налаштування

### Settings Class

```python
from src.conf.config import settings

# API Keys
settings.OPENROUTER_API_KEY.get_secret_value()
settings.MANYCHAT_API_KEY.get_secret_value()

# Database
settings.DATABASE_URL.get_secret_value()

# LLM Configuration
settings.AI_MODEL           # "gpt-4o-mini"
settings.LLM_TEMPERATURE    # 0.7
settings.LLM_MAX_TOKENS     # 1024

# Feature Flags
settings.ENABLE_PAYMENT_HITL       # Human-in-the-loop для оплати
settings.ENABLE_MEMORY_EXTRACTION  # Витяг фактів з діалогу
settings.DEBUG_TRACE_LOGS          # Verbose logging
```

### Валідація

Settings автоматично валідуються при старті:
- Перевірка обов'язкових API ключів
- Перевірка URL форматів
- Виведення попереджень про відсутні опціональні налаштування

---

## 💳 payment_config.py — Платіжні реквізити

```python
from src.conf.payment_config import (
    PAYMENT_PREPAY_AMOUNT,
    format_requisites_multiline,
    format_requisites_with_receipt_request,
)

# Сума передоплати
PAYMENT_PREPAY_AMOUNT  # 200 грн

# Форматування реквізитів
format_requisites_multiline()
# → "ПриватБанк: 5168 XXXX XXXX XXXX\nОтримувач: ТОВ Mirt"
```

---

## 📝 Вердикт

Це **фундамент** всієї системи.
Без `config.py` жоден модуль не знає, до якого API підключатися.

**Конфліктів немає.** Один напрямок залежностей: всі → conf.
