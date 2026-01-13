# ⚙️ src/workers — Celery Background Tasks

> **Роль:** "Background Engine"
> **Відповідальність:** Асинхронна обробка задач (summarization, followups, LLM usage tracking).

Workers працюють **паралельно** з HTTP сервером і обробляють довготривалі операції.

---

## 📊 Архітектурна Позиція

```
┌─────────────────────────────────────────────────────────────┐
│                     DEPENDENCY PYRAMID                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│     src/server/                                              │
│          ↓                                                   │
│   ━━━━ src/workers/ ━━━━  ← YOU ARE HERE                    │
│          ↓                                                   │
│     src/agents/      src/integrations/                      │
│          ↓                ↓                                  │
│     src/services/                                            │
│          ↓                                                   │
│     src/core/                                                │
│          ↓                                                   │
│     src/conf/                                                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Структура

```
src/workers/
├── celery_app.py       # 🔧 Celery configuration (queues, beat, signals)
├── dispatcher.py       # 📤 High-level task dispatchers
├── exceptions.py       # ⚠️ Worker-specific exceptions (Retryable, Permanent)
├── idempotency.py      # 🔁 Idempotency key management
├── sync_utils.py       # 🔄 run_sync() for async-in-sync
└── tasks/              # 📋 Task definitions
    ├── followups.py        # Follow-up messages (scheduled)
    ├── summarization.py    # Session summarization
    ├── messages.py         # Message processing
    ├── llm_usage.py        # LLM usage tracking & billing
    ├── memory.py           # Memory cleanup
    ├── health.py           # Health check tasks
    ├── manychat.py         # ManyChat processing
    └── postgres_helpers.py # DB utilities
```

---

## 📚 Детальний Опис

### 🔧 `celery_app.py` — Celery Configuration

**Черги (Queues):**

| Queue | Routing Key | Призначення |
| :--- | :--- | :--- |
| `default` | `default` | Загальні задачі |
| `summarization` | `summarization` | Summarization сесій |
| `followups` | `followups` | Follow-up повідомлення |

**Beat Schedule:**
```python
celery_app.conf.beat_schedule = {
    "cleanup-expired-memory": {"task": "...", "schedule": crontab(hour=3)},
    "health-check": {"task": "...", "schedule": 60.0},
}
```

**Signals:**
- `worker_init_handler` — Startup logging
- `task_failure_handler` — Error tracking

---

### 📤 `dispatcher.py` — Task Dispatchers

High-level API для запуску задач:

```python
from src.workers.dispatcher import (
    dispatch_summarization,
    dispatch_followup,
)

# Dispatch summarization
dispatch_summarization(session_id="123")

# Dispatch followup
dispatch_followup(session_id="123")
```

---

### ⚠️ `exceptions.py` — Worker Exceptions

| Exception | Retry? | Призначення |
| :--- | :--- | :--- |
| `WorkerError` | — | Base exception |
| `RetryableError` | ✅ | Temporary failure (retry) |
| `PermanentError` | ❌ | Fatal error (no retry) |
| `DatabaseError` | ✅ | DB connection issues |
| `RateLimitError` | ✅ | Rate limit hit |
| `ExternalServiceError` | ✅ | External API failure |
| `IdempotencyError` | ❌ | Duplicate task |

---

### 📋 Tasks

#### `tasks/followups.py` — Follow-up Messages

| Task | Призначення |
| :--- | :--- |
| `check_followup_due` | Перевірка, чи потрібен follow-up |
| `send_followup` | Відправка follow-up |
| `run_all_followups` | Batch processing всіх pending |

#### `tasks/summarization.py` — Session Summarization

| Task | Призначення |
| :--- | :--- |
| `summarize_session` | Summarization однієї сесії |
| `cleanup_old_summaries` | Очистка старих summaries |

#### `tasks/llm_usage.py` — LLM Usage Tracking

| Task | Призначення |
| :--- | :--- |
| `log_llm_usage` | Запис LLM токенів/вартості |
| `aggregate_daily_usage` | Денна агрегація |
| `bill_overdue_usage` | Billing reports |

#### `tasks/messages.py` — Message Processing

| Task | Призначення |
| :--- | :--- |
| `process_message` | Обробка повідомлення через AI graph |

#### `tasks/memory.py` — Memory Cleanup

| Task | Призначення |
| :--- | :--- |
| `cleanup_expired_memory` | Видалення expired facts |

---

## 🛡️ Правила Архітектури

| Правило | Статус |
| :--- | :--- |
| `workers → services` | ✅ Дозволено |
| `workers → core` | ✅ Дозволено |
| `workers → conf` | ✅ Дозволено |
| `workers → integrations` | ✅ Дозволено |
| `workers → agents` | ✅ Дозволено (викликає graph) |
| `workers → server` | ⚠️ **1 порушення** (див. нижче) |

---

## ⚠️ Знайдена Проблема

**Файл:** `tasks/manychat.py`

```python
from src.server.dependencies import get_session_store  # ⚠️ VIOLATION
```

**Проблема:** Workers не повинні залежати від Server.
**Рішення:** Перемістити `get_session_store()` до `services/storage`.

---

## 📝 Вердикт

`src/workers` — **майже чистий**.
Одна незначна проблема з імпортом `server.dependencies`.
Рекомендується рефакторинг для повної чистоти.
