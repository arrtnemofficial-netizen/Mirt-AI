# ManyChat Push Mode (Async Architecture)

## 🧠 Огляд

MIRT тепер підтримує **два режими** роботи з ManyChat:

| Режим | Переваги | Недоліки |
|-------|----------|----------|
| **Push Mode** (default) | Немає timeout, надійніше | Потрібен ManyChat API key |
| **Response Mode** | Простіше налаштувати | Timeout 30s, може зависнути |

## 🏗️ Архітектура Push Mode

```
ManyChat → POST /webhooks/manychat
                    ↓
              return {"status": "accepted"} (202)
                    ↓ (background task)
              ManyChatAsyncService
                    ↓
              Debouncer (3 sec wait)
                    ↓
              LangGraph processing
                    ↓
              ManyChatPushClient
                    ↓
ManyChat ← POST api.manychat.com/fb/sending/sendContent
```

## ⚙️ Налаштування

### 1. Environment Variables

```env
# .env
MANYCHAT_API_KEY=your-api-key-from-manychat
MANYCHAT_API_URL=https://api.manychat.com
MANYCHAT_VERIFY_TOKEN=your-shared-secret
MANYCHAT_PUSH_MODE=true
```

### 2. Отримати ManyChat API Key

1. Зайти в ManyChat → Settings → API
2. Натиснути "Get API Key"
3. Скопіювати ключ в `MANYCHAT_API_KEY`

### 3. Налаштувати ManyChat Webhook

**Request URL:** `https://your-domain.com/webhooks/manychat`

**Headers:**
| Key | Value |
|-----|-------|
| `Content-Type` | `application/json` |
| `X-ManyChat-Token` | `your-shared-secret` |

**Body:**
```json
{
  "subscriber": {
    "id": "{{id}}"
  },
  "message": {
    "text": "{{last_input_text}}"
  },
  "type": "instagram"
}
```

## 📦 Компоненти

### ManyChatPushClient
`src/integrations/manychat/push_client.py`

Низькорівневий клієнт для відправки повідомлень через ManyChat API:
- `send_content()` - повна відправка з полями, тегами, quick replies
- `send_text()` - проста текстова відповідь

### ManyChatAsyncService
`src/integrations/manychat/async_service.py`

Високорівневий сервіс, який:
- Обробляє debouncing (3 сек)
- Конвертує AgentResponse в ManyChat формат
- Зберігає всі MIRT фічі:
  - Custom Fields (ai_state, ai_intent, etc.)
  - Tags (ai_responded, needs_human, etc.)
  - Quick Replies (state-based buttons)
  - Images (product photos)

## 🔄 Режими

### Push Mode (MANYCHAT_PUSH_MODE=true)
```python
# Webhook повертає одразу
return {"status": "accepted"}

# Обробка в background task
background_tasks.add_task(
    service.process_message_async,
    user_id=user_id,
    text=text,
    ...
)
```

### Response Mode (MANYCHAT_PUSH_MODE=false)
```python
# Чекає на AI і повертає відповідь
return await handler.handle(payload)
```

## 🧪 Тестування через Ngrok

```bash
# Terminal 1: Start server
python -m uvicorn src.server.main:app --port 8000

# Terminal 2: Start ngrok
ngrok http 8000

# Use ngrok URL in ManyChat
# Example: https://abc123.ngrok-free.app/webhooks/manychat
```

## ⚠️ Відомі обмеження

1. **PushClient enabled=False** якщо `MANYCHAT_API_KEY` не налаштований
2. **Background tasks** втрачаються при перезапуску сервера
3. **Для production** рекомендується Celery замість Background Tasks

## 📊 Порівняння з WizaLive

| Feature | MIRT | WizaLive |
|---------|------|----------|
| Debouncing | ✅ 3 sec | ❌ |
| Images | ✅ | ❌ |
| Custom Fields | ✅ 8 полів | ❌ |
| Tags | ✅ 4 теги | ✅ 1 тег |
| Quick Replies | ✅ State-based | ❌ |
| Async Push | ✅ | ✅ |
| Work Hours | ❌ | ✅ |

## 📝 Evidence Log

**E1:** Створено push_client.py, async_service.py
**E2:** Оновлено webhook endpoint в main.py з підтримкою двох режимів
**E3:** Перевірено імпорти: `python -c "from src.integrations.manychat import *"` ✅
**E4:** Config параметри працюють: `MANYCHAT_PUSH_MODE=True` ✅
