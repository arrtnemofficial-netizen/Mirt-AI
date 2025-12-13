# Sitniks CRM Integration

## Огляд

Інтеграція MIRT AI з Sitniks CRM для автоматичного оновлення статусів чатів.

## Статуси

| Stage | Sitniks Status | Коли спрацьовує | Дія |
|-------|---------------|-----------------|-----|
| `first_touch` | Взято в роботу | Перше повідомлення від клієнта | + Встановити відповідального = AI Manager (Павло) |
| `give_requisites` | Виставлено рахунок | Показ реквізитів для оплати | — |
| `escalation` | AI Увага | Будь-яка ескалація | + Переключити на живого менеджера |

## Архітектура

### Файли

```
src/integrations/crm/
├── sitniks_chat_service.py  # Основний сервіс для чатів
├── snitkix.py               # Сервіс для замовлень
└── migrations/
    └── 002_add_sitniks_chat_id.sql  # SQL міграція
```

### Таблиці в Supabase

```sql
-- Маппінг MIRT користувачів на Sitniks чати
CREATE TABLE sitniks_chat_mappings (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,           -- MIRT session_id
    instagram_username TEXT,         -- Instagram @username
    telegram_username TEXT,          -- Telegram @username
    sitniks_chat_id TEXT UNIQUE,     -- ID чату в Sitniks
    sitniks_manager_id INTEGER,      -- ID менеджера
    current_status TEXT,             -- Поточний статус
    first_touch_at TIMESTAMP,        -- Час першого контакту
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

## Інтеграція в LangGraph

Виклики Sitniks вбудовані в існуючі ноди:

### 1. First Touch (memory_context_node)

```python
# memory.py
if step_number <= 1:
    sitniks_result = await sitniks_service.handle_first_touch(
        user_id=session_id,
        instagram_username=instagram_username,
        telegram_username=telegram_username,
    )
```

### 2. Invoice Sent (payment_node)

```python
# payment.py (перед interrupt)
await sitniks_service.handle_invoice_sent(session_id)
```

### 3. Escalation (escalation_node)

```python
# escalation.py
sitniks_result = await sitniks_service.handle_escalation(session_id)
```

## Алгоритм пошуку чату

1. При першому повідомленні беремо `user_nickname` (Telegram username)
2. Запитуємо `/open-api/chats` за останні 5 хвилин
3. Шукаємо чат де `userNickName` == наш username
4. Зберігаємо `sitniks_chat_id` в `sitniks_chat_mappings`

## Налаштування

### .env

```bash
SNITKIX_API_URL=https://crm.sitniks.com
SNITKIX_API_KEY=your_api_key_here
```

### Supabase

Виконай SQL міграцію:

```sql
-- Запусти в Supabase SQL Editor
\i src/integrations/crm/migrations/002_add_sitniks_chat_id.sql
```

## Важливо

### API Access

⚠️ **Sitniks API потребує платного плану!**

На безкоштовному (trial) плані отримаєш `403 Forbidden`.

### Менеджери

Для першого запуску:
1. Зайди в Sitniks → Менеджери
2. Знайди ID менеджера "Павло" (AI Manager)
3. Знайди ID живого менеджера для ескалацій

Або система автоматично знайде їх через API `/open-api/managers`.

## Тестування

### Локальне тестування (без API)

```python
# Статуси працюють через логіку в коді
# Навіть без API вони просто логуються
SNITKIX_API_URL=  # залишаємо пустим
```

### З реальним API

```python
# Запусти тест
python -c "
import asyncio
from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service

async def test():
    service = get_sitniks_chat_service()
    print('Enabled:', service.enabled)
    if service.enabled:
        managers = await service.get_managers()
        print('Managers:', managers)

asyncio.run(test())
"
```

## Діаграма потоку

```
Telegram Message
       │
       ▼
┌─────────────────┐
│ moderation_node │
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ memory_context_node │──► Sitniks: "Взято в роботу" (first touch)
└────────┬────────────┘
         │
         ▼
    [graph flow]
         │
         ▼
┌─────────────────┐
│  payment_node   │──► Sitniks: "Виставлено рахунок" (show payment)
└────────┬────────┘
         │
         ▼
    [if escalation]
         │
         ▼
┌─────────────────┐
│ escalation_node │──► Sitniks: "AI Увага" + assign human manager
└─────────────────┘
```

## Помилки та обробка

Всі виклики Sitniks обгорнуті в try/except:

```python
try:
    await sitniks_service.handle_first_touch(...)
except Exception as e:
    logger.warning("Sitniks error: %s", e)
    # Граф продовжує роботу
```

Помилки Sitniks **не блокують** основний потік діалогу.
